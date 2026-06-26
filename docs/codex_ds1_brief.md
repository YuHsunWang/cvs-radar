# Codex 任務：LLM 情感後端上線（接 OpenAI API）（ds1）

> Claude 已拍板。Codex 執行，完成後 Claude 獨立驗證。**先單獨跑測試確認綠燈再 commit（勿串同條指令）。**

## 背景

`sentiment.py` 已有完整的 `LlmBackend` 架構（`LlmSentimentClient` protocol、fallback 機制、API key 管理），但目前 `enabled=False` 且沒有實際的 client 實作。需要：

1. 實作一個用 OpenAI API（GPT 模型）的 `LlmSentimentClient`
2. 更新 `config.py` 預設值為 OpenAI provider
3. 讓使用者只需設定環境變數 `CVS_RADAR_LLM_API_KEY` 即可啟用

現有架構已處理好 fallback（API 不可用時降級到 `snownlp`）、error handling、和 `clamp` 到 [-1, 1]，所以只需要實作 client 的 `score_text` 方法。

## 只能改的檔案

- `cvs_radar/sentiment.py` — 新增 `OpenAiSentimentClient` 類別
- `cvs_radar/config.py` — 更新 LLM 預設配置
- `requirements.txt` — 加入 `openai` 依賴
- `tests/test_core.py` — 新增 LLM client 測試
- **不可改其他檔案**

## 任務 A：實作 `OpenAiSentimentClient`

在 `sentiment.py` 新增：

```python
class OpenAiSentimentClient:
    """LlmSentimentClient implementation using OpenAI chat completions."""

    def score_text(self, text: str, *, provider: str, model: str, api_key: str) -> float:
        import openai

        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model or "gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一個台灣超商食品評論的情感分析器。"
                        "使用者會給你一則 PTT CVS 版的留言，請判斷情感分數。"
                        "規則：\n"
                        "- 回傳一個浮點數，範圍 -1.0（極負面）到 1.0（極正面）\n"
                        "- 0.0 表示中性\n"
                        "- 注意反諷語氣（例如「好棒喔，貴到可以當精品」是負面）\n"
                        "- 注意 PTT 用語（例如「雷」=負面、「回購」=正面）\n"
                        "- 只回傳數字，不要其他文字"
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0.0,
            max_tokens=10,
        )
        raw = (response.choices[0].message.content or "").strip()
        return float(raw)
```

修改 `LlmBackend.__init__` 預設使用 `OpenAiSentimentClient`：

```python
class LlmBackend:
    name = "llm"

    def __init__(
        self,
        *,
        client: LlmSentimentClient | None = None,
        fallback: SentimentBackend | None = None,
    ) -> None:
        if client is None:
            try:
                client = OpenAiSentimentClient()
            except Exception:
                client = None
        self.client = client
        self.fallback = fallback or _backend_from_name(
            _llm_config().get("fallback_backend", "snownlp"), allow_llm=False
        )
```

注意：`import openai` 放在 `score_text` 方法內部（lazy import），避免未安裝 `openai` 時 import `sentiment.py` 就 crash。

## 任務 B：更新 `config.py`

更新 `SENTIMENT` 的 LLM 配置：

```python
SENTIMENT = {
    "backend": "lexicon",
    "tag_prior_weight": 0.6,
    "llm": {
        "enabled": False,
        "provider": "openai",
        "model": "gpt-4o-mini",
        "api_key": "",
        "api_key_env": "CVS_RADAR_LLM_API_KEY",
        "fallback_backend": "snownlp",
    },
}
```

變更：`provider` 從空字串改為 `"openai"`、`model` 從空字串改為 `"gpt-4o-mini"`。

## 任務 C：更新 `requirements.txt`

加入 openai SDK：

```
openai>=1.0
```

## 任務 D：新增測試

在 `tests/test_core.py` 的適當 TestCase 類別中新增：

```python
def test_openai_client_parses_float_response(self) -> None:
    """OpenAiSentimentClient.score_text returns float from API response."""
    from unittest.mock import MagicMock, patch
    from cvs_radar.sentiment import OpenAiSentimentClient

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "0.75"

    client = OpenAiSentimentClient()
    with patch("openai.OpenAI") as mock_openai:
        mock_openai.return_value.chat.completions.create.return_value = mock_response
        score = client.score_text("好吃會回購", provider="openai", model="gpt-4o-mini", api_key="test-key")

    self.assertAlmostEqual(score, 0.75)

def test_openai_client_negative_response(self) -> None:
    """OpenAiSentimentClient handles negative scores."""
    from unittest.mock import MagicMock, patch
    from cvs_radar.sentiment import OpenAiSentimentClient

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "-0.8"

    client = OpenAiSentimentClient()
    with patch("openai.OpenAI") as mock_openai:
        mock_openai.return_value.chat.completions.create.return_value = mock_response
        score = client.score_text("難吃踩雷", provider="openai", model="gpt-4o-mini", api_key="test-key")

    self.assertAlmostEqual(score, -0.8)

def test_llm_backend_fallback_when_no_key(self) -> None:
    """LlmBackend falls back to snownlp when no API key is set."""
    import os
    from unittest.mock import patch
    from cvs_radar.sentiment import LlmBackend

    with patch.dict(os.environ, {}, clear=True):
        backend = LlmBackend()
        score = backend.text_score("好吃")
        # Should get a score from fallback (snownlp or lexicon), not raise
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, -1.0)
        self.assertLessEqual(score, 1.0)

def test_llm_backend_fallback_on_api_error(self) -> None:
    """LlmBackend falls back when API call raises."""
    from unittest.mock import MagicMock, patch
    from cvs_radar.sentiment import LlmBackend, OpenAiSentimentClient

    client = OpenAiSentimentClient()
    with patch.object(client, "score_text", side_effect=Exception("API error")):
        backend = LlmBackend(client=client)
        with patch.dict("os.environ", {"CVS_RADAR_LLM_API_KEY": "test"}):
            with patch("cvs_radar.config.SENTIMENT", {
                "backend": "llm",
                "tag_prior_weight": 0.6,
                "llm": {"enabled": True, "provider": "openai", "model": "gpt-4o-mini",
                         "api_key": "", "api_key_env": "CVS_RADAR_LLM_API_KEY",
                         "fallback_backend": "lexicon"},
            }):
                score = backend.text_score("好吃")
    self.assertIsInstance(score, float)
```

## 驗收

- 所有既有測試 + 新測試全過（不需要真的有 OpenAI API key，測試用 mock）
- `OpenAiSentimentClient` 能正確 parse API 回傳的浮點數字串
- `LlmBackend` 在沒有 API key 時 graceful fallback 到 snownlp
- `LlmBackend` 在 API error 時 graceful fallback
- `config.py` 的 LLM 設定指向 OpenAI provider 和 gpt-4o-mini model
- `requirements.txt` 包含 `openai>=1.0`
- lazy import：不安裝 openai 套件時，`from cvs_radar.sentiment import LexiconBackend` 不會 crash
- 先跑測試確認綠燈再 commit，不要 push
