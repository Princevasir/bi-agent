from app.llm.base import LLMResult


class FakeLLM:
    def generate(self, prompt: str) -> LLMResult:
        words = len(prompt.split())
        return LLMResult(text=f"Echo: {prompt}", input_tokens=words, output_tokens=words + 1)