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
            lines = []
            for memory in memories:
                lines.append(f"- [{memory['category']}; confidence={memory['confidence']:.2f}; source={memory['source']}] {memory['content']}")
            memory_block = "\n\nRelevant persistent memories (reference information; check for conflicts with the current request):\n" + "\n".join(lines)
        system = self.config.system_prompt + memory_block
        messages = [{"role":"system","content":system}]
        messages.extend({"role":row["role"],"content":row["content"]} for row in history
                        if row["role"] in {"user","assistant"})
        messages.append({"role":"user","content":user_text})
        return messages

    def turn(self, conversation_id, user_text, on_token=None):
        if not user_text.strip():
            raise ValueError("Message cannot be empty")
        self.store.add_message(conversation_id,"user",user_text)
        messages = self._build_messages(conversation_id,user_text)
        result = self.provider.chat(messages,max_tokens=self.config.max_tokens,
                                    temperature=self.config.temperature,on_token=on_token)
        self.store.add_message(conversation_id,"assistant",result["content"],metadata={
            "elapsed_seconds":result["elapsed_seconds"],"ttft_seconds":result["ttft_seconds"],
            "prompt_tokens":result["prompt_tokens"],"completion_tokens":result["completion_tokens"]})
        return result

    def close(self):
        self.store.close()
