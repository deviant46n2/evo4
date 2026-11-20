import re
from .provider import OpenAICompatibleProvider
from .store import EvoStore

class EvoAssistant:
    def __init__(self, config, store=None, provider=None):
        self.config = config
        self.store = store or EvoStore(config.database)
        self.provider = provider or OpenAICompatibleProvider(config.base_url,config.api_key,
                                                               config.model,config.timeout_seconds)

    def new_conversation(self, title="New conversation"):
        return self.store.create_conversation(title)

    def _build_messages(self, conversation_id, user_text):
        memories = self.store.search_memories(user_text,self.config.memory_limit)
        history = self.store.get_messages(conversation_id,self.config.history_messages)
        memory_block = ""
        if memories:
            lines = [f"- [{m['category']}; confidence={m['confidence']:.2f}; source={m['source']}] {m['content']}"
                     for m in memories]
            memory_block = "\n\nRelevant persistent memories (reference information; check for conflicts with the current request):\n" + "\n".join(lines)
        messages = [{"role":"system","content":self.config.system_prompt + memory_block}]
        messages.extend({"role":row["role"],"content":row["content"]} for row in history
                        if row["role"] in {"user","assistant"})
        messages.append({"role":"user","content":user_text})
        return messages

    def _capture_memory_candidate(self, conversation_id, user_text):
        patterns = [
            (r"^(?:i prefer|i like|i love|i dislike|i hate|i avoid)\\s+(.+)$","preferences",0.75),
            (r"^(?:my goal is|i want to|i plan to|i intend to)\\s+(.+)$","goals",0.65),
            (r"^my project is\\s+(.+)$","projects",0.8),
            (r"^(?:i use|i work with|my setup is)\\s+(.+)$","environment",0.7),
        ]
        explicit = re.match(r"^remember that\\s+(.+)$",user_text.strip(),re.IGNORECASE)
        if explicit and len(explicit.group(1).strip()) >= 8:
            return self.store.add_memory(explicit.group(1).strip(),category="explicit",source="explicit-user",confidence=1.0)
        for pattern,category,confidence in patterns:
            match = re.match(pattern,user_text.strip(),re.IGNORECASE)
            if match:
                content = match.group(1).strip()
                if len(content) >= 16 and not content.lower().startswith(("to know","to understand","to ask")):
                    return self.store.propose_memory(content,category,source="conversation:user",conversation_id=conversation_id,confidence=confidence)
        return None

    def turn(self, conversation_id, user_text, on_token=None):
        if not user_text.strip():
            raise ValueError("Message cannot be empty")
        # Build context before persisting this turn so the current user message is not duplicated.
        messages = self._build_messages(conversation_id,user_text)
        self.store.add_message(conversation_id,"user",user_text)
        self._capture_memory_candidate(conversation_id,user_text)
        result = self.provider.chat(messages,max_tokens=self.config.max_tokens,
                                    temperature=self.config.temperature,on_token=on_token)
        self.store.add_message(conversation_id,"assistant",result["content"],metadata={
            "elapsed_seconds":result["elapsed_seconds"],"ttft_seconds":result["ttft_seconds"],
            "prompt_tokens":result["prompt_tokens"],"completion_tokens":result["completion_tokens"]})
        return result

    def close(self):
        self.store.close()
