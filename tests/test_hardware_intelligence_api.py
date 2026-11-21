import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from evo_core.api import create_app, RuntimeProfileInput, WorkloadAssessment
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

@unittest.skipUnless(AVAILABLE, "FastAPI desktop dependencies are not installed")
class HardwareIntelligenceApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        root=Path(self.temp.name)
        self.config=root/"config.toml"
        self.config.write_text(f'[server]\nbase_url="http://127.0.0.1:18997"\nmodel="test-model"\n[experiment]\ndatabase="{root / "evo.sqlite3"}"\n')
        self.app=create_app(self.config)
        self.routes={(r.path, method):r.endpoint for r in self.app.routes if hasattr(r,"endpoint") for method in (r.methods or [])}

    def tearDown(self):
        self.app.state.assistant.close()
        self.app.state.lab_db.close()
        self.temp.cleanup()

    def test_profile_api_persists_runtime_record(self):
        payload=RuntimeProfileInput(name="Qwen baseline",model="qwen",context_size=49152,gpu_layers="all",kv_cache_k="q4_0")
        saved=self.routes[("/api/v1/hardware/profiles","POST")](payload)
        self.assertEqual(saved["name"],"Qwen baseline")
        self.assertEqual(self.routes[("/api/v1/hardware/profiles","GET")]()[0]["id"],saved["id"])

    def test_estimate_api_accepts_architecture_and_reports_unknown_fit(self):
        payload=RuntimeProfileInput(name="estimate",context_size=4096,layers=32,kv_heads=8,head_dim=128)
        sample={"gpu_memory_total_mib":16384,"gpu_memory_used_mib":4096,"ram_available_bytes":8*1024**3}
        with patch("evo_core.api.sample_nvidia_smi",return_value=sample):
            result=self.routes[("/api/v1/hardware/estimate","POST")](payload)
        self.assertIsNotNone(result["kv_cache_mib_estimate"])
        self.assertEqual(result["vram_free_mib"],12288)
        self.assertEqual(result["fit_assessment"],"unknown")

    def test_admission_api_defers_when_reserve_would_be_breached(self):
        payload=WorkloadAssessment(kind="benchmark",estimated_vram_mib=4000)
        sample={"gpu_memory_total_mib":16384,"gpu_memory_used_mib":12000,"ram_available_bytes":8*1024**3}
        with patch("evo_core.api.sample_nvidia_smi",return_value=sample):
            result=self.routes[("/api/v1/hardware/admission","POST")](payload)
        self.assertEqual(result["decision"],"defer")
        self.assertFalse(result["process_actions"])

    def test_runtime_discovery_reports_config_separately(self):
        with patch("evo_core.api.sample_nvidia_smi",return_value={"gpu_processes":[]}):
            result=self.routes[("/api/v1/hardware/runtimes","GET")]()
        self.assertEqual(result["configured_endpoint"]["model"],"test-model")
        self.assertEqual(result["processes"],[])

    def test_capabilities_disclose_no_process_control(self):
        caps=self.routes[("/api/v1/capabilities","GET")]()
        self.assertTrue(caps["hardware_runtime_discovery"])
        self.assertFalse(caps["hardware_process_control"])

if __name__=="__main__":
    unittest.main()
