#!/usr/bin/env python3
"""
短期株価予測 Web アプリ
FastAPI + SSE でリアルタイムに分析結果をストリーミング配信します。

起動:
    uvicorn app:app --reload
    → http://localhost:8000
"""

import os
import re
import json
import asyncio
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import anthropic
import short_term_predictor as stp

app = FastAPI(title="短期株価予測 AI")
templates = Jinja2Templates(directory="templates")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# ==============================================================================
# 定数
# ==============================================================================

def build_chat_system() -> str:
    from datetime import datetime
    today = datetime.now().strftime("%Y年%m月%d日")
    return f"""あなたは短期株式投資のアドバイザーAIです。
本日は{today}です。

このシステムはユーザーが銘柄を推薦するリクエストをした際に、yfinanceを使って
リアルタイムの株価・テクニカル指標・ニュース・アナリスト評価を自動取得して分析します。
あなたの学習データのカットオフ日時に関わらず、取得したリアルタイムデータを元に分析が行われます。

【重要】
- 「知識が古い」「データがない」などと断らないでください
- ユーザーが直近の株価動向や最新トレンドについて聞いた場合も、銘柄を推薦してください
- 推薦後にシステムが自動でリアルタイムデータを取得・分析します

【ルール】
- 最初のメッセージでは簡潔に挨拶し、投資スタイルや興味を1〜2個質問してください
- 1〜2回の会話でユーザーの希望を把握し、3〜6銘柄を推薦してください
- 推薦の準備ができたら、回答文の末尾に必ず以下のJSONブロックを付けてください:
  {{"tickers": ["NVDA", "MSFT", "7203.T"]}}
- 米国株はティッカーシンボル（例: NVDA）、日本株は証券コード+".T"（例: 7203.T）で指定してください
- 日本株と米国株を混在させることも可能です
- 会話はすべて日本語で行ってください
- 推薦理由は簡潔に（各銘柄1〜2文）説明してください"""

# ==============================================================================
# ヘルパー
# ==============================================================================

def result_to_dict(result: stp.StockAnalysis) -> dict:
    return {
        "ticker":        result.ticker,
        "company_name":  result.company_name,
        "current_price": result.current_price,
        "currency":      result.currency,
        "sector":        result.sector,
        "final_score":   result.final_score,
        "recommendation": result.recommendation,
        "summary":       result.summary,
        "error":         result.error,
        "agent_results": [
            {
                "name":       r.name,
                "key":        r.key,
                "score":      r.score,
                "confidence": r.confidence,
                "reasoning":  r.reasoning,
                "signals":    r.signals,
            }
            for r in result.agent_results
        ],
    }


def extract_tickers(text: str) -> list[str]:
    """レスポンステキストから {"tickers": [...]} を抽出する（米国株・日本株対応）"""
    match = re.search(r'\{[^{}]*"tickers"\s*:\s*\[([^\]]*)\][^{}]*\}', text)
    if not match:
        return []
    raw = match.group(1)
    tickers = [t.strip().strip('"').strip("'").upper() for t in raw.split(",")]
    # 米国株: NVDA / 日本株: 7203.T
    return [t for t in tickers if re.match(r'^[A-Z]{1,5}$', t) or re.match(r'^\d{4}\.T$', t)]


async def run_analysis(ticker_list: list[str], model: str, queue: asyncio.Queue):
    """銘柄リストを並行分析してキューに結果を流す"""
    stp.MODEL = model
    stp.SUPPORTS_THINKING = "haiku" not in model

    async_client = anthropic.AsyncAnthropic()
    semaphore    = asyncio.Semaphore(3)

    async def run_one(ticker: str):
        async with semaphore:
            await queue.put({"type": "analysis_progress", "ticker": ticker})
            result = await stp.analyze_stock(async_client, ticker)
            await queue.put({"type": "analysis_result", "ticker": ticker, "data": result_to_dict(result)})

    tasks = [asyncio.create_task(run_one(t)) for t in ticker_list]
    await asyncio.gather(*tasks, return_exceptions=True)
    await queue.put({"type": "analysis_done"})


# ==============================================================================
# リクエストモデル
# ==============================================================================

class ChatRequest(BaseModel):
    messages: list[dict]
    model: str = "claude-haiku-4-5-20251001"


# ==============================================================================
# ルーティング
# ==============================================================================

@app.get("/health")
async def health_check():
    """App Runnerヘルスチェック用エンドポイント"""
    return {"status": "healthy"}

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/chat")
async def chat(req: ChatRequest):
    async def generate():
        client     = anthropic.AsyncAnthropic()
        full_text  = ""

        # ── Claude のレスポンスをストリーミング（529 リトライあり）──
        for attempt in range(3):
            try:
                async with client.messages.stream(
                    model      = req.model,
                    max_tokens = 1024,
                    system     = build_chat_system(),
                    messages   = req.messages,
                ) as stream:
                    async for chunk in stream:
                        if chunk.type == "content_block_delta" and hasattr(chunk.delta, "text"):
                            token = chunk.delta.text
                            full_text += token
                            yield f"data: {json.dumps({'type': 'text', 'content': token}, ensure_ascii=False)}\n\n"
                break  # 成功したらリトライループを抜ける
            except anthropic.APIStatusError as e:
                if e.status_code == 529 and attempt < 2:
                    wait = 10 * (attempt + 1)
                    retry_msg = f"(サーバー混雑中、{wait}秒後にリトライします...)\n"
                    yield f"data: {json.dumps({'type': 'text', 'content': retry_msg}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(wait)
                    full_text = ""
                    continue
                yield f"data: {json.dumps({'type': 'text', 'content': 'Anthropic サーバーが混雑しています。Haiku または Sonnet に切り替えてお試しください。'}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
                return

        yield f"data: {json.dumps({'type': 'text_done'}, ensure_ascii=False)}\n\n"

        # ── ティッカー抽出 → 分析 ──
        tickers = extract_tickers(full_text)
        if tickers:
            yield f"data: {json.dumps({'type': 'recommend', 'tickers': tickers}, ensure_ascii=False)}\n\n"

            queue: asyncio.Queue = asyncio.Queue()
            analysis_task = asyncio.create_task(run_analysis(tickers, req.model, queue))

            done = False
            while not done:
                item = await queue.get()
                if item["type"] == "analysis_done":
                    done = True
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

            await analysis_task

        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
