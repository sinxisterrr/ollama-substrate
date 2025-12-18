#!/usr/bin/env python3
"""
Ollama Cloud API Client for Substrate AI

Drop-in replacement for OpenRouterClient that uses Ollama Cloud instead.
Same interface, different provider!

Usage:
    from core.ollama_client import OllamaClient
    client = OllamaClient(api_key="your_ollama_key")
"""

import os
import json
import aiohttp
import asyncio
from typing import Optional, Dict, List, Any, AsyncGenerator
from dataclasses import dataclass
from datetime import datetime


@dataclass
class TokenUsage:
    """Token usage tracking (mimics OpenRouter structure)"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0


class OllamaError(Exception):
    """Ollama API errors"""
    def __init__(self, message: str, status_code: Optional[int] = None, 
                 response_body: Optional[str] = None, context: Optional[Dict] = None):
        self.status_code = status_code
        self.response_body = response_body
        self.context = context or {}
        
        full_message = f"\n{'='*60}\n"
        full_message += f"❌ OLLAMA ERROR\n"
        full_message += f"{'='*60}\n\n"
        full_message += f"🔴 Problem: {message}\n\n"
        
        if status_code:
            full_message += f"📊 Status Code: {status_code}\n"
            
        if response_body:
            full_message += f"💬 Response: {response_body[:200]}...\n"
        
        if context:
            full_message += f"\n📋 Context:\n"
            for key, value in context.items():
                full_message += f"   • {key}: {value}\n"
        
        full_message += f"\n💡 Suggestions:\n"
        
        if status_code == 401:
            full_message += "   • Check your OLLAMA_API_KEY in .env\n"
            full_message += "   • Get key at: https://ollama.com\n"
        elif status_code == 429:
            full_message += "   • You're being rate limited\n"
            full_message += "   • Wait a few seconds and retry\n"
        elif status_code == 400:
            full_message += "   • Check your message format\n"
            full_message += "   • Model might not exist\n"
        else:
            full_message += "   • Check Ollama Cloud status\n"
            full_message += "   • Try again in a few seconds\n"
        
        full_message += f"\n{'='*60}\n"
        super().__init__(full_message)


class OllamaClient:
    """
    Ollama Cloud API client - DROP-IN REPLACEMENT for OpenRouterClient
    
    Same interface, same methods, just uses Ollama instead!
    """
    
    def __init__(
        self,
        api_key: str,
        default_model: str = "llama3.1:70b",
        app_name: str = "SubstrateAI",
        app_url: Optional[str] = None,
        timeout: int = 60,
        cost_tracker = None
    ):
        """
        Initialize Ollama client.
        
        Args:
            api_key: Ollama Cloud API key
            default_model: Default model to use
            app_name: App name (for headers)
            app_url: App URL (for headers)
            timeout: Request timeout in seconds
            cost_tracker: Optional CostTracker instance
        """
        if not api_key:
            raise OllamaError(
                "Missing Ollama API key",
                context={"how_to_get": "Get one at https://ollama.com"}
            )
        
        self.api_key = api_key
        self.default_model = default_model
        self.app_name = app_name
        self.app_url = app_url
        self.timeout = timeout
        self.base_url = "https://ollama.com/api"
        
        # Cost tracking (minimal for Ollama)
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_cost = 0.0
        self.cost_tracker = cost_tracker
        
        print(f"✅ Ollama Client initialized")
        print(f"   Model: {default_model}")
        print(f"   Timeout: {timeout}s")
    
    def _get_headers(self) -> Dict[str, str]:
        """Build request headers"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.8,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Non-streaming chat completion.
        
        Args:
            messages: List of message dicts
            model: Model to use
            temperature: Sampling temperature
            max_tokens: Max tokens to generate
            tools: Tool definitions (Ollama doesn't support these yet)
            **kwargs: Additional parameters
            
        Returns:
            Response dict in OpenRouter format
            
        Raises:
            OllamaError: If request fails
        """
        model = model or self.default_model
        url = f"{self.base_url}/chat"
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
            }
        }
        
        # Add max tokens if specified
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        
        print(f"\n📡 Calling Ollama: {model}")
        
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                async with session.post(url, headers=self._get_headers(), json=payload) as response:
                    
                    if response.status != 200:
                        body = await response.text()
                        raise OllamaError(
                            "Request failed",
                            status_code=response.status,
                            response_body=body,
                            context={"model": model}
                        )
                    
                    data = await response.json()
                    
                    # Convert Ollama response to OpenRouter format
                    message_content = data.get("message", {}).get("content", "")
                    
                    # Extract token counts if available
                    prompt_tokens = data.get("prompt_eval_count", 0)
                    completion_tokens = data.get("eval_count", 0)
                    
                    # Track usage
                    self.total_prompt_tokens += prompt_tokens
                    self.total_completion_tokens += completion_tokens
                    
                    # Log to persistent tracker if available
                    if self.cost_tracker and (prompt_tokens > 0 or completion_tokens > 0):
                        # Ollama is typically free or very cheap
                        input_cost = 0.0
                        output_cost = 0.0
                        self.cost_tracker.log_request(
                            model=model,
                            input_tokens=prompt_tokens,
                            output_tokens=completion_tokens,
                            input_cost=input_cost,
                            output_cost=output_cost
                        )
                    
                    # Return in OpenRouter format
                    return {
                        "id": data.get("id", f"ollama-{datetime.utcnow().timestamp()}"),
                        "model": model,
                        "created": int(datetime.utcnow().timestamp()),
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": message_content
                                },
                                "finish_reason": "stop"
                            }
                        ],
                        "usage": {
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                            "total_tokens": prompt_tokens + completion_tokens
                        }
                    }
        
        except aiohttp.ClientError as e:
            raise OllamaError(
                f"Network error: {str(e)}",
                context={"model": model}
            )
    
    async def stream_chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Stream chat completion.
        
        Args:
            messages: List of message dicts
            model: Model to use
            tools: Tool definitions
            **kwargs: Additional parameters
            
        Yields:
            Delta dicts from streaming response
            
        Raises:
            OllamaError: If request fails
        """
        model = model or self.default_model
        url = f"{self.base_url}/chat"
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            **kwargs
        }
        
        print(f"\n📡 Streaming from Ollama: {model}")
        
        try:
            stream_timeout = aiohttp.ClientTimeout(
                total=None,
                sock_read=60.0,
                sock_connect=10.0
            )
            
            async with aiohttp.ClientSession(timeout=stream_timeout) as session:
                async with session.post(url, headers=self._get_headers(), json=payload) as response:
                    
                    if response.status != 200:
                        body = await response.text()
                        raise OllamaError(
                            "Streaming failed",
                            status_code=response.status,
                            response_body=body,
                            context={"model": model}
                        )
                    
                    # Stream chunks
                    chunk_count = 0
                    async for line in response.content:
                        chunk_count += 1
                        line = line.decode('utf-8').strip()
                        
                        if not line:
                            continue
                        
                        try:
                            data = json.loads(line)
                            
                            # Convert Ollama streaming format to OpenRouter format
                            message = data.get("message", {})
                            content = message.get("content", "")
                            
                            if content:
                                # Yield in OpenRouter SSE format
                                yield {
                                    "id": f"ollama-stream-{chunk_count}",
                                    "object": "chat.completion.chunk",
                                    "created": int(datetime.utcnow().timestamp()),
                                    "model": model,
                                    "choices": [
                                        {
                                            "index": 0,
                                            "delta": {
                                                "role": "assistant",
                                                "content": content
                                            },
                                            "finish_reason": None
                                        }
                                    ]
                                }
                            
                            # Check if done
                            if data.get("done", False):
                                print(f"🏁 Stream complete! Total chunks: {chunk_count}")
                                break
                        
                        except json.JSONDecodeError:
                            continue
        
        except aiohttp.ClientError as e:
            raise OllamaError(
                f"Network error during streaming: {str(e)}",
                context={"model": model}
            )
    
    def parse_tool_calls(self, response: Dict[str, Any]) -> List:
        """
        Parse tool calls from response.
        Ollama doesn't support tool calling yet, so this returns empty list.
        """
        return []
    
    def get_stats(self) -> Dict[str, Any]:
        """Get usage statistics"""
        return {
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
            "estimated_cost_usd": self.total_cost
        }
    
    async def get_models(self) -> List[Dict[str, Any]]:
        """
        Get available Ollama models.
        Note: This uses local API, not cloud API
        """
        # For Ollama Cloud, we'd need a different endpoint
        # For now, return empty list or common models
        return [
            {"id": "llama3.1:70b", "name": "Llama 3.1 70B"},
            {"id": "llama3.1:8b", "name": "Llama 3.1 8B"},
            {"id": "qwen2.5:72b", "name": "Qwen 2.5 72B"},
            {"id": "qwen2.5:32b", "name": "Qwen 2.5 32B"},
        ]


# Testing
async def test_ollama_client():
    """Test the Ollama client"""
    print("\n🧪 TESTING OLLAMA CLIENT")
    print("="*60)
    
    api_key = os.getenv("OLLAMA_API_KEY")
    
    if not api_key:
        print("❌ No OLLAMA_API_KEY found in environment")
        return
    
    try:
        client = OllamaClient(api_key=api_key)
    except OllamaError as e:
        print(e)
        return
    
    # Test simple chat
    print("\n💬 Test: Simple chat")
    try:
        response = await client.chat_completion(
            messages=[
                {"role": "user", "content": "Say 'Hello from Ollama!' and nothing else."}
            ]
        )
        
        message = response['choices'][0]['message']['content']
        print(f"✅ Response: {message}")
        print(f"✅ Tokens: {response['usage']['total_tokens']}")
    except OllamaError as e:
        print(e)
        return
    
    # Stats
    print("\n📊 Stats:")
    stats = client.get_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")
    
    print("\n✅ TEST PASSED!")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(test_ollama_client())