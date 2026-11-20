from pathlib import Path
import fnmatch
import subprocess
import time

IGNORED_DIRS={".git",".venv","venv","__pycache__","node_modules",".mypy_cache",".pytest_cache","dist","build"}
SENSITIVE_NAMES={".env",".env.local",".env.production",".npmrc",".pypirc","config.toml","config.local.toml",
                 "id_rsa","id_dsa","id_ecdsa","id_ed25519","credentials","credentials.json","credentials.yaml",
                 "secrets.json","secrets.yaml","secrets.yml"}

def _is_excluded(path):
    return any(part in IGNORED_DIRS or part in SENSITIVE_NAMES or
               part == ".env" or part.startswith(".env.") or
               part.endswith((".pem",".key",".p12",".pfx")) for part in path.parts)

class WorkspaceError(RuntimeError):
    pass

class Workspace:
    """Constrained project workspace API intended for future agent tools.

    All paths are resolved beneath root. Commands are argv arrays (never shell strings)
    and must match an explicitly configured command prefix.
    """
    def __init__(self,root,allowed_commands=(),max_read_bytes=2_000_000):
        self.root=Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise WorkspaceError(f"Workspace root is not a directory: {self.root}")
        self.allowed_commands=[tuple(item) for item in allowed_commands if item]
        self.max_read_bytes=max_read_bytes

    def resolve(self,relative_path):
        candidate=(self.root / relative_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceError("Path escapes the configured workspace") from exc
        return candidate

    def list_files(self,relative_path=".",pattern="*",limit=500):
        base=self.resolve(relative_path)
        if not base.is_dir():
            raise WorkspaceError(f"Not a directory: {relative_path}")
        results=[]
        for path in base.rglob("*"):
            if any(part in IGNORED_DIRS for part in path.relative_to(self.root).parts):
                continue
            if not path.is_symlink() and path.is_file() and not _is_excluded(path.relative_to(self.root)) and fnmatch.fnmatch(path.name,pattern):
                results.append(path.relative_to(self.root).as_posix())
                if len(results)>=max(1,limit):
                    break
        return results

    def read_file(self,relative_path):
        path=self.resolve(relative_path)
        if not path.is_file():
            raise WorkspaceError(f"File not found: {relative_path}")
        if _is_excluded(path.relative_to(self.root)):
            raise WorkspaceError("Refusing to expose ignored, configuration, or credential files to the model")
        size=path.stat().st_size
        if size>self.max_read_bytes:
            raise WorkspaceError(f"File is {size} bytes; limit is {self.max_read_bytes}")
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceError("File is not UTF-8 text") from exc

    def search_text(self,query,relative_path=".",limit=100):
        if not query:
            raise ValueError("Search query cannot be empty")
        matches=[]
        for name in self.list_files(relative_path,limit=10000):
            path=self.resolve(name)
            try:
                if path.stat().st_size>self.max_read_bytes:
                    continue
                lines=path.read_text(encoding="utf-8").splitlines()
            except (OSError,UnicodeDecodeError):
                continue
            for number,line in enumerate(lines,1):
                if query.casefold() in line.casefold():
                    matches.append({"path":name,"line":number,"text":line[:500]})
                    if len(matches)>=max(1,limit):
                        return matches
        return matches

    def write_file(self,relative_path,content,overwrite=False):
        path=self.resolve(relative_path)
        if _is_excluded(path.relative_to(self.root)):
            raise WorkspaceError("Refusing to write inside ignored or sensitive paths")
        if path.exists() and not overwrite:
            raise WorkspaceError("File already exists; pass overwrite=True to replace it")
        path.parent.mkdir(parents=True,exist_ok=True)
        # Resolve again after parent creation to guard against pre-existing symlink parents.
        path=self.resolve(relative_path)
        path.write_text(content,encoding="utf-8")
        return path.relative_to(self.root).as_posix()

    def run(self,argv,timeout_seconds=120):
        if not isinstance(argv,(list,tuple)) or not argv or not all(isinstance(x,str) for x in argv):
            raise ValueError("Command must be a nonempty argv list of strings")
        allowed=any(tuple(argv[:len(prefix)])==prefix for prefix in self.allowed_commands)
        if not allowed:
            raise WorkspaceError("Command is not allowlisted. Configure an explicit command prefix first.")
        started=time.monotonic()
        try:
            result=subprocess.run(list(argv),cwd=self.root,text=True,encoding="utf-8",
                                  errors="replace",capture_output=True,timeout=max(1,min(int(timeout_seconds),900)),
                                  shell=False)
        except subprocess.TimeoutExpired as exc:
            raise WorkspaceError(f"Command timed out after {timeout_seconds}s") from exc
        return {"argv":list(argv),"returncode":result.returncode,"stdout":result.stdout[-20000:],
                "stderr":result.stderr[-20000:],"elapsed_seconds":time.monotonic()-started}
