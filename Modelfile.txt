# Optimized Modelfile for LocalLarry-Fast on RTX 4060 8GB

FROM LocalLarry-Fast:latest

TEMPLATE """
{{- if .System }}
<|im_start|>system
{{ .System }}
<|im_end|>
{{- end }}
{{- range .Messages }}
{{- if eq .Role "user" }}
<|im_start|>user
{{ .Content }}
<|im_end|>
{{- else if eq .Role "assistant" }}
<|im_start|>assistant
{{ .Content }}
<|im_end|>
{{- else if eq .Role "tool" }}
<|im_start|>user
<tool_response>
{{ .Content }}
</tool_response>
<|im_end|>
{{- end }}
{{- end }}
<|im_start|>assistant
"""

SYSTEM """You are LocalLarry-Fast, a fast and reliable sub-agent of LARRY G-FORCE.
You excel at quick responses, tool calling, code execution, file operations, and simple reasoning.
You have strong tool-calling capabilities. Always use the exact JSON format for tools.

For complex, long-context, or deep reasoning tasks, clearly state that you are escalating to the main 15B model.
Be concise, accurate, and honest. Never fabricate tool results."""

# Hardware-Optimized Parameters
PARAMETER num_ctx 32768          # Longer context (32K tokens)
PARAMETER num_gpu 35             # Safe for 8GB VRAM (leaves headroom)
PARAMETER num_thread 16          # Balanced for 64GB DDR5
PARAMETER num_predict -1         # No limit on output length
PARAMETER temperature 0.3        # More focused / deterministic
PARAMETER top_p 0.95
PARAMETER top_k 40
PARAMETER repeat_penalty 1.1
PARAMETER stop <|im_start|>
PARAMETER stop <|im_end|>

# Tool Calling Emphasis
PARAMETER stop <tool_call>
PARAMETER stop </tool_call>