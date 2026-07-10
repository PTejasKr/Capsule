import logging
import httpx
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI
from backend.config import settings

logger = logging.getLogger("capsule.routing_service")

class MultiProviderRouter:
    def __init__(self):
        self.providers = []
        
        if settings.GEMINI_API_KEY:
            self.providers.append({
                "name": "gemini",
                "client": AsyncOpenAI(
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                    api_key=settings.GEMINI_API_KEY
                ),
                "model": "gemini-1.5-flash"
            })
            
        if settings.GROQ_API_KEY:
            self.providers.append({
                "name": "groq",
                "client": AsyncOpenAI(
                    base_url="https://api.groq.com/openai/v1",
                    api_key=settings.GROQ_API_KEY
                ),
                "model": "llama-3.3-70b-versatile"
            })
            
        if settings.NVIDIA_NIM_API_KEY:
            self.providers.append({
                "name": "nvidia_nim",
                "client": AsyncOpenAI(
                    base_url=settings.NVIDIA_NIM_BASE_URL,
                    api_key=settings.NVIDIA_NIM_API_KEY
                ),
                "model": settings.NVIDIA_NIM_MODEL
            })
            
        if settings.OPENROUTER_API_KEY:
            self.providers.append({
                "name": "openrouter",
                "client": AsyncOpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=settings.OPENROUTER_API_KEY
                ),
                "model": "meta-llama/llama-3-8b-instruct:free"
            })
            
        if settings.OLLAMA_BASE_URL:
            self.providers.append({
                "name": "ollama",
                "client": AsyncOpenAI(
                    base_url=settings.OLLAMA_BASE_URL,
                    api_key="ollama"  # Ollama doesn't require an API key
                ),
                "model": "llama3.1"
            })

    async def chat_completion(
        self, 
        messages: List[Dict[str, str]], 
        temperature: float = 0.1, 
        response_format: Optional[Dict[str, str]] = None,
        max_tokens: int = 2000,
        specific_provider: Optional[str] = None
    ) -> str:
        """
        Executes a chat completion query by cascading through available free providers.
        """
        if not self.providers:
            raise RuntimeError("No AI providers configured in settings.")
            
        providers_to_try = self.providers
        if specific_provider:
            providers_to_try = [p for p in self.providers if p["name"] == specific_provider]
            if not providers_to_try:
                raise ValueError(f"Requested provider '{specific_provider}' is not configured.")

        last_error = None
        
        for provider in providers_to_try:
            name = provider["name"]
            client: AsyncOpenAI = provider["client"]
            model = provider["model"]
            
            logger.info(f"Attempting inference with provider: {name} (model: {model})")
            
            try:
                kwargs = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                
                if response_format and name != "ollama":
                    kwargs["response_format"] = response_format
                    
                response = await client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content
                logger.info(f"Success with provider: {name}")
                return content
                
            except Exception as e:
                error_msg = str(e)
                logger.warning(f"Provider {name} failed: {error_msg}. Switching to next provider...")
                last_error = e
                continue
                
        logger.error("All configured AI providers failed.")
        raise RuntimeError(f"All AI providers failed. Last error: {last_error}")

router_service = MultiProviderRouter()
