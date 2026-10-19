from app.llm.base import LLMResult


class RoutedLLM:
    def __init__(self, sql, answer="North was 270.", rewrite=""):
        self.sql, self.answer, self.rewrite = sql, answer, rewrite
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        if prompt.startswith("Rewrite"):
            text = self.rewrite
        elif prompt.startswith("You write PostgreSQL"):
            text = self.sql
        else:
            text = self.answer
        return LLMResult(text=text, input_tokens=1, output_tokens=1)