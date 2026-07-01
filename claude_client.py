import os
import anthropic

class ClaudeClient:
    def __init__(self):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def generate_reply(self, messages: list, system_prompt: str) -> str:
        if not self.is_configured():
            return "Anthropic API key is not configured."
        
        client = anthropic.Anthropic(api_key=self.api_key)
        try:
            response = client.messages.create(
                model="claude-opus-4-8",
                max_tokens=2048,
                system=system_prompt,
                messages=messages,
                thinking={"type": "adaptive"}
            )
            
            reply = ""
            for block in response.content:
                if block.type == "text":
                    reply += block.text
            return reply
        except Exception as e:
            return f"Error communicating with Claude: {str(e)}"
