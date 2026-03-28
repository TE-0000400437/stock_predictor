#!/usr/bin/env python3
"""
株価予測マルチエージェントシステム
4専門エージェント + オーケストレーターで6ヶ月後の上昇銘柄を予測します。

使い方:
    python stock_predictor.py                    # デフォルト銘柄リストを分析
    python stock_predictor.py NVDA MSFT AAPL    # 指定銘柄を分析

環境変数:
    ANTHROPIC_API_KEY  (必須)
"""

import os
import sys
import json
import re
import asyncio
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

import anthropic
import yfinance as yf
import pandas as pd
import numpy as np
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

# ==============================================================================
# 設定
# ==============================================================================

MODEL = "claude-opus-4-6"
console = Console()

# エージェントの重み（オーケストレーターが参考にする基本値）
AGENT_WEIGHTS = {
    "fundamental": 0.30,
    "technical":   0.25,
    "sentiment":   0.25,
    "macro":       0.20,
}

# ==============================================================================
# データ構造
# ==============================================================================

@dataclass
class AgentResult:
    name: str
    key: str
    score: float        # 0-100
    confidence: str     # 高/中/低
    reasoning: str
    signals: list[str]


@dataclass
class StockAnalysis:
    ticker: str
    company_name: str
    current_price: float
    sector: str = ""
    agent_results: list[AgentResult] = field(default_factory=list)
    final_score: float = 0.0
    recommendation: str = ""
    summary: str = ""
    error: Optional[str] = None


# ==============================================================================
# ユーティリティ
# ==============================================================================

def extract_json(text: str) -> dict:
    """テキストからJSONオブジェクトを安全に抽出する"""
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)

    start = text.find('{')
    if start == -1:
        return {}

    depth = 0
    end = -1
    for i in range(start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                end = i
                break

    if end == -1:
        return {}

    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}


def get_text_block(response) -> str:
    """レスポンスからテキストブロックを取得する（thinkingブロックは除外）"""
    for block in response.content:
        if block.type == "text":
            return block.text
    return ""


def fmt(val, spec=".2f", prefix="", suffix="", divisor=1, na="N/A") -> str:
    """値を安全にフォーマットする"""
    try:
        if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
            return na
        return f"{prefix}{val / divisor:{spec}}{suffix}"
    except Exception:
        return str(val) if val is not None else na


def score_to_recommendation(score: float) -> str:
    if score >= 75: return "強い買い"
    if score >= 62: return "買い"
    if score >= 48: return "中立"
    if score >= 35: return "売り"
    return "強い売り"


# ==============================================================================
# データ取得・前処理
# ==============================================================================

def fetch_stock_data(ticker: str) -> dict:
    """yfinanceで株式の全データを取得しテクニカル指標を計算する"""
    stock = yf.Ticker(ticker)
    hist = stock.history(period="1y")
    info = stock.info

    financials = balance_sheet = cash_flow = None
    try:
        financials   = stock.financials
        balance_sheet = stock.balance_sheet
        cash_flow    = stock.cashflow
    except Exception:
        pass

    news = []
    try:
        news = stock.news[:10]
    except Exception:
        pass

    # テクニカル指標の計算
    if not hist.empty and len(hist) >= 20:
        close = hist['Close']

        # 移動平均
        hist['SMA20']  = close.rolling(20).mean()
        hist['SMA50']  = close.rolling(50).mean()
        hist['SMA200'] = close.rolling(200).mean()

        # RSI (14)
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
        rs = gain / (loss + 1e-10)
        hist['RSI'] = 100 - (100 / (1 + rs))

        # MACD (12/26/9)
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        hist['MACD']        = ema12 - ema26
        hist['MACD_Signal'] = hist['MACD'].ewm(span=9, adjust=False).mean()
        hist['MACD_Hist']   = hist['MACD'] - hist['MACD_Signal']

        # ボリンジャーバンド (20, ±2σ)
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        hist['BB_upper'] = sma20 + 2 * std20
        hist['BB_mid']   = sma20
        hist['BB_lower'] = sma20 - 2 * std20

    return {
        "ticker":        ticker,
        "info":          info,
        "history":       hist,
        "financials":    financials,
        "balance_sheet": balance_sheet,
        "cash_flow":     cash_flow,
        "news":          news,
    }


def prepare_fundamental_context(data: dict) -> str:
    info = data["info"]
    lines = [
        "=== ファンダメンタル指標 ===",
        f"企業名: {info.get('longName', info.get('shortName', 'N/A'))}",
        f"セクター: {info.get('sector', 'N/A')} / {info.get('industry', 'N/A')}",
        "",
        "--- バリュエーション ---",
        f"時価総額:         {fmt(info.get('marketCap'), '.1f', '$', 'B', 1e9)}",
        f"PER（実績）:      {fmt(info.get('trailingPE'))}",
        f"PER（予想）:      {fmt(info.get('forwardPE'))}",
        f"PBR:              {fmt(info.get('priceToBook'))}",
        f"PSR:              {fmt(info.get('priceToSalesTrailing12Months'))}",
        f"EV/EBITDA:        {fmt(info.get('enterpriseToEbitda'))}",
        f"PEGレシオ:        {fmt(info.get('pegRatio'))}",
        "",
        "--- 収益性 ---",
        f"粗利率:           {fmt(info.get('grossMargins'), '.1%')}",
        f"営業利益率:       {fmt(info.get('operatingMargins'), '.1%')}",
        f"純利益率:         {fmt(info.get('profitMargins'), '.1%')}",
        f"ROE:              {fmt(info.get('returnOnEquity'), '.1%')}",
        f"ROA:              {fmt(info.get('returnOnAssets'), '.1%')}",
        "",
        "--- 成長性 ---",
        f"売上成長率(YoY):  {fmt(info.get('revenueGrowth'), '.1%')}",
        f"EPS成長率(YoY):   {fmt(info.get('earningsGrowth'), '.1%')}",
        f"フォワードEPS:    {fmt(info.get('forwardEps'))}",
        "",
        "--- 財務健全性 ---",
        f"D/Eレシオ:        {fmt(info.get('debtToEquity'))}",
        f"流動比率:         {fmt(info.get('currentRatio'))}",
        f"現金:             {fmt(info.get('totalCash'), '.1f', '$', 'B', 1e9)}",
        f"総負債:           {fmt(info.get('totalDebt'), '.1f', '$', 'B', 1e9)}",
        f"フリーCF:         {fmt(info.get('freeCashflow'), '.1f', '$', 'B', 1e9)}",
        "",
        "--- 株価情報 ---",
        f"現在株価:         {fmt(info.get('currentPrice'), '.2f', '$')}",
        f"52週高値:         {fmt(info.get('fiftyTwoWeekHigh'), '.2f', '$')}",
        f"52週安値:         {fmt(info.get('fiftyTwoWeekLow'), '.2f', '$')}",
        f"配当利回り:       {fmt(info.get('dividendYield'), '.2%')}",
        f"EPS:              {fmt(info.get('trailingEps'))}",
    ]

    # 財務サマリー（直近期）
    if data["financials"] is not None and not data["financials"].empty:
        try:
            fin = data["financials"]
            lines += ["", "--- 財務データ（直近期比較） ---"]
            if "Total Revenue" in fin.index:
                rev = fin.loc["Total Revenue"].dropna()
                if len(rev) >= 2:
                    g = (rev.iloc[0] - rev.iloc[1]) / abs(rev.iloc[1]) * 100
                    lines.append(f"売上高: {fmt(rev.iloc[0], '.1f', '$', 'B', 1e9)} (前年比: {g:+.1f}%)")
            if "Net Income" in fin.index:
                ni = fin.loc["Net Income"].dropna()
                if len(ni) >= 1:
                    lines.append(f"純利益: {fmt(ni.iloc[0], '.1f', '$', 'B', 1e9)}")
        except Exception:
            pass

    return "\n".join(lines)


def prepare_technical_context(data: dict) -> str:
    hist = data["history"]
    if hist.empty:
        return "価格データなし"

    latest = hist.iloc[-1]
    cp = float(latest['Close'])

    def pct(n):
        if len(hist) > n:
            old = float(hist.iloc[-n - 1]['Close'])
            return f"{(cp - old) / old * 100:+.2f}%"
        return "N/A"

    lines = [
        "=== テクニカル指標 ===",
        f"現在株価: ${cp:.2f}",
        "",
        "--- 価格パフォーマンス ---",
        f"1週間:  {pct(5)}",
        f"1ヶ月:  {pct(22)}",
        f"3ヶ月:  {pct(66)}",
        f"6ヶ月:  {pct(132)}",
        f"1年:    {pct(len(hist) - 1)}",
        "",
        "--- 移動平均線 ---",
    ]

    for col, label in [("SMA20", "SMA20"), ("SMA50", "SMA50"), ("SMA200", "SMA200")]:
        if col in hist.columns:
            v = latest.get(col)
            if v is not None and not (isinstance(v, float) and np.isnan(v)):
                pos = "上方" if cp > float(v) else "下方"
                lines.append(f"{label}: ${float(v):.2f}  (現在株価は{pos})")

    if 'RSI' in hist.columns:
        rsi = latest.get('RSI')
        if rsi is not None and not (isinstance(rsi, float) and np.isnan(rsi)):
            rsi = float(rsi)
            label = "買われすぎ" if rsi > 70 else "売られすぎ" if rsi < 30 else "中立圏"
            lines += ["", f"RSI(14): {rsi:.1f}  ({label})"]

    if 'MACD' in hist.columns:
        macd = latest.get('MACD')
        sig  = latest.get('MACD_Signal')
        hist_v = latest.get('MACD_Hist')
        if macd is not None and sig is not None:
            try:
                cross = "ゴールデンクロス圏" if float(macd) > float(sig) else "デッドクロス圏"
                lines += [
                    "",
                    f"MACD:           {float(macd):.4f}",
                    f"MACDシグナル:   {float(sig):.4f}",
                    f"ヒストグラム:   {float(hist_v):.4f}  ({cross})",
                ]
            except Exception:
                pass

    if 'BB_upper' in hist.columns:
        bu = latest.get('BB_upper')
        bm = latest.get('BB_mid')
        bl = latest.get('BB_lower')
        if bu is not None and bl is not None:
            try:
                bu, bm, bl = float(bu), float(bm), float(bl)
                pct_bb = (cp - bl) / (bu - bl) * 100 if bu != bl else 50
                lines += [
                    "",
                    "--- ボリンジャーバンド ---",
                    f"上限: ${bu:.2f}  中間: ${bm:.2f}  下限: ${bl:.2f}",
                    f"バンド内位置: {pct_bb:.1f}%  (0%=下限, 100%=上限)",
                ]
            except Exception:
                pass

    avg_vol = float(hist['Volume'].mean())
    last_vol = float(latest['Volume'])
    vol_ratio = last_vol / avg_vol if avg_vol > 0 else 1.0
    lines += [
        "",
        "--- 出来高 ---",
        f"直近出来高:     {last_vol:,.0f}",
        f"平均出来高(1年):{avg_vol:,.0f}",
        f"出来高比率:     {vol_ratio:.2f}x",
    ]

    returns = hist['Close'].pct_change().dropna()
    if len(returns) > 10:
        vol = float(returns.std()) * np.sqrt(252) * 100
        lines += ["", f"年率ボラティリティ: {vol:.1f}%"]

    return "\n".join(lines)


def prepare_sentiment_context(data: dict) -> str:
    info = data["info"]
    news = data["news"]

    lines = [
        "=== センチメント情報 ===",
        "",
        "--- アナリスト評価 ---",
        f"推奨スコア:       {info.get('recommendationMean', 'N/A')}  (1=強買い, 5=強売り)",
        f"推奨キー:         {info.get('recommendationKey', 'N/A')}",
        f"アナリスト数:     {info.get('numberOfAnalystOpinions', 'N/A')}",
        f"目標株価（平均）: {fmt(info.get('targetMeanPrice'), '.2f', '$')}",
        f"目標株価（高値）: {fmt(info.get('targetHighPrice'), '.2f', '$')}",
        f"目標株価（安値）: {fmt(info.get('targetLowPrice'), '.2f', '$')}",
        f"現在株価:         {fmt(info.get('currentPrice'), '.2f', '$')}",
    ]

    target  = info.get('targetMeanPrice')
    current = info.get('currentPrice')
    if target and current and float(current) > 0:
        upside = (float(target) - float(current)) / float(current) * 100
        lines.append(f"目標価格との乖離: {upside:+.1f}%")

    inst = info.get('institutionalOwnershipPercentage') or info.get('heldPercentInstitutions')
    lines += [
        "",
        "--- 機関投資家・空売り ---",
        f"機関投資家保有率: {fmt(inst, '.1%')}",
        f"空売り残高(日数): {fmt(info.get('shortRatio'))}",
        f"空売り比率:       {fmt(info.get('shortPercentOfFloat'), '.1%')}",
        "",
        "--- 企業概要 ---",
    ]

    summary = info.get('longBusinessSummary', '')
    if summary:
        lines.append(summary[:600])

    if news:
        lines += ["", "--- 最新ニュース ---"]
        for i, article in enumerate(news[:7], 1):
            title     = article.get('title', 'N/A')
            publisher = article.get('publisher', '')
            lines.append(f"{i}. {title}  [{publisher}]")

    return "\n".join(lines)


def prepare_macro_context(data: dict) -> str:
    info = data["info"]

    lines = [
        "=== マクロ/セクター情報 ===",
        "",
        "--- 企業基本情報 ---",
        f"セクター:    {info.get('sector', 'N/A')}",
        f"業界:        {info.get('industry', 'N/A')}",
        f"国:          {info.get('country', 'N/A')}",
        f"従業員数:    {info.get('fullTimeEmployees', 'N/A')}",
        "",
        "--- バリュエーション比較 ---",
        f"フォワードPER: {fmt(info.get('forwardPE'))}",
        f"PEGレシオ:     {fmt(info.get('pegRatio'))}",
        f"EV/EBITDA:     {fmt(info.get('enterpriseToEbitda'))}",
        f"EV/Revenue:    {fmt(info.get('enterpriseToRevenue'))}",
        "",
        "--- 成長期待 ---",
        f"売上成長率予測:  {fmt(info.get('revenueGrowth'), '.1%')}",
        f"EPS成長率(YoY): {fmt(info.get('earningsGrowth'), '.1%')}",
        f"フォワードEPS:   {fmt(info.get('forwardEps'))}",
        "",
        "--- 財務健全性 ---",
        f"総現金:           {fmt(info.get('totalCash'), '.1f', '$', 'B', 1e9)}",
        f"総負債:           {fmt(info.get('totalDebt'), '.1f', '$', 'B', 1e9)}",
        f"フリーCF:         {fmt(info.get('freeCashflow'), '.1f', '$', 'B', 1e9)}",
        f"営業CF:           {fmt(info.get('operatingCashflow'), '.1f', '$', 'B', 1e9)}",
        "",
        "--- 株主還元 ---",
        f"配当利回り:   {fmt(info.get('dividendYield'), '.2%')}",
        f"配当性向:     {fmt(info.get('payoutRatio'), '.1%')}",
        "",
        "--- リスク指標 ---",
        f"ベータ値:     {fmt(info.get('beta'))}",
    ]

    return "\n".join(lines)


# ==============================================================================
# AIエージェント
# ==============================================================================

RESPONSE_SCHEMA = """{
    "score": <0〜100の整数>,
    "confidence": "<高|中|低>",
    "reasoning": "<分析理由（日本語200文字以上）>",
    "signals": ["<シグナル1>", "<シグナル2>", "<シグナル3>"]
}"""


async def run_agent(
    async_client: anthropic.AsyncAnthropic,
    ticker: str,
    key: str,
    name: str,
    system: str,
    context: str,
) -> AgentResult:
    """汎用エージェント実行"""
    prompt = f"""以下は{ticker}の{name}データです。

{context}

6ヶ月後の株価上昇可能性を0〜100で評価してください。
（80以上=強い上昇見込み / 60-79=上昇見込み / 40-59=中立 / 20-39=下落リスク / 20未満=強い下落リスク）

以下のJSON形式のみで回答してください（説明文不要）:
{RESPONSE_SCHEMA}"""

    try:
        response = await async_client.messages.create(
            model=MODEL,
            max_tokens=1024,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = get_text_block(response)
        data = extract_json(text)

        return AgentResult(
            name=name,
            key=key,
            score=float(data.get("score", 50)),
            confidence=data.get("confidence", "低"),
            reasoning=data.get("reasoning", text[:400]),
            signals=data.get("signals", []),
        )
    except Exception as e:
        return AgentResult(
            name=name, key=key,
            score=50.0, confidence="低",
            reasoning=f"エラー: {e}", signals=[],
        )


async def fundamental_agent(ac, ticker, ctx):
    return await run_agent(
        ac, ticker, "fundamental", "ファンダメンタル分析",
        ("あなたは株式のファンダメンタル分析専門家です。"
         "財務指標・収益性・成長性・バリュエーションを総合的に評価し、"
         "6ヶ月後の株価上昇可能性を判断します。必ずJSON形式のみで回答してください。"),
        ctx,
    )


async def technical_agent(ac, ticker, ctx):
    return await run_agent(
        ac, ticker, "technical", "テクニカル分析",
        ("あなたは株式のテクニカル分析専門家です。"
         "移動平均・RSI・MACD・ボリンジャーバンド・出来高・トレンドを分析し、"
         "6ヶ月後の価格動向を評価します。必ずJSON形式のみで回答してください。"),
        ctx,
    )


async def sentiment_agent(ac, ticker, ctx):
    return await run_agent(
        ac, ticker, "sentiment", "センチメント分析",
        ("あなたは株式市場のセンチメント分析専門家です。"
         "アナリスト評価・機関投資家動向・ニュース・空売り状況を分析し、"
         "市場の期待が6ヶ月後の株価に与える影響を評価します。必ずJSON形式のみで回答してください。"),
        ctx,
    )


async def macro_agent(ac, ticker, ctx):
    return await run_agent(
        ac, ticker, "macro", "マクロ/バリュエーション分析",
        ("あなたはマクロ経済とセクター分析の専門家です。"
         "セクタートレンド・相対バリュエーション・マクロ環境・競合比較を分析し、"
         "6ヶ月の投資時間軸での魅力度を評価します。必ずJSON形式のみで回答してください。"),
        ctx,
    )


async def orchestrator_agent(
    async_client: anthropic.AsyncAnthropic,
    ticker: str,
    company_name: str,
    agent_results: list[AgentResult],
) -> tuple[float, str, str]:
    """オーケストレーター: 全エージェントの結果を統合して最終判断を下す"""

    # フォールバック用の加重平均スコア
    key_map = {r.key: r.score for r in agent_results}
    weighted = sum(key_map.get(k, 50) * w for k, w in AGENT_WEIGHTS.items())

    summary_text = "\n\n".join(
        f"【{r.name}】スコア: {r.score:.0f}/100  信頼度: {r.confidence}\n"
        f"分析: {r.reasoning[:400]}\n"
        f"シグナル: {' | '.join(r.signals[:3])}"
        for r in agent_results
    )

    prompt = f"""以下は{company_name}({ticker})の各専門エージェント分析結果です。

{summary_text}

基本加重平均スコア (FA30%/TA25%/センチ25%/マクロ20%): {weighted:.1f}

これらを統合し、6ヶ月後の株価見通しの最終判断を行ってください。
各エージェントの信頼性や相互補完性を考慮し、適切に重み調整してください。

以下のJSON形式のみで回答してください:
{{
    "final_score": <0〜100の整数>,
    "recommendation": "<強い買い|買い|中立|売り|強い売り>",
    "summary": "<総合投資判断（日本語400文字以上）>",
    "key_catalysts": ["<主要上昇要因1>", "<主要上昇要因2>", "<主要リスク1>"]
}}

推奨基準: 75以上→強い買い, 62-74→買い, 48-61→中立, 35-47→売り, 35未満→強い売り"""

    try:
        response = await async_client.messages.create(
            model=MODEL,
            max_tokens=2048,
            thinking={"type": "adaptive"},
            system=(
                "あなたは経験豊富な株式投資アナリストです。"
                "複数の専門エージェントの分析を統合し、バランスの取れた最終投資判断を提供します。"
                "必ずJSON形式のみで回答してください。"
            ),
            messages=[{"role": "user", "content": prompt}],
        )
        text = get_text_block(response)
        data = extract_json(text)

        return (
            float(data.get("final_score", weighted)),
            data.get("recommendation", score_to_recommendation(weighted)),
            data.get("summary", ""),
        )
    except Exception as e:
        return weighted, score_to_recommendation(weighted), f"統合分析エラー: {e}"


# ==============================================================================
# メイン分析フロー
# ==============================================================================

async def analyze_stock(
    async_client: anthropic.AsyncAnthropic,
    ticker: str,
) -> StockAnalysis:
    """1銘柄の完全分析パイプライン"""

    try:
        data = fetch_stock_data(ticker)
    except Exception as e:
        return StockAnalysis(
            ticker=ticker, company_name=ticker,
            current_price=0.0, error=f"データ取得失敗: {e}",
        )

    info = data["info"]
    company_name = info.get("longName") or info.get("shortName") or ticker
    sector = info.get("sector", "N/A")

    current_price = float(info.get("currentPrice") or 0)
    if not current_price and not data["history"].empty:
        current_price = float(data["history"].iloc[-1]["Close"])

    # コンテキスト準備
    fund_ctx  = prepare_fundamental_context(data)
    tech_ctx  = prepare_technical_context(data)
    senti_ctx = prepare_sentiment_context(data)
    macro_ctx = prepare_macro_context(data)

    # 4エージェントを並行実行
    raw_results = await asyncio.gather(
        fundamental_agent(async_client, ticker, fund_ctx),
        technical_agent(async_client, ticker, tech_ctx),
        sentiment_agent(async_client, ticker, senti_ctx),
        macro_agent(async_client, ticker, macro_ctx),
        return_exceptions=True,
    )

    valid_results = [r for r in raw_results if isinstance(r, AgentResult)]

    if not valid_results:
        return StockAnalysis(
            ticker=ticker, company_name=company_name,
            current_price=current_price, sector=sector,
            error="全エージェントが失敗しました",
        )

    # オーケストレーターで統合
    final_score, recommendation, summary = await orchestrator_agent(
        async_client, ticker, company_name, valid_results
    )

    return StockAnalysis(
        ticker=ticker,
        company_name=company_name,
        current_price=current_price,
        sector=sector,
        agent_results=valid_results,
        final_score=final_score,
        recommendation=recommendation,
        summary=summary,
    )


# ==============================================================================
# 結果表示
# ==============================================================================

def display_results(analyses: list[StockAnalysis]) -> None:
    valid  = sorted([a for a in analyses if not a.error], key=lambda x: x.final_score, reverse=True)
    errors = [a for a in analyses if a.error]

    rec_styles = {
        "強い買い": "bold green",
        "買い":     "green",
        "中立":     "yellow",
        "売り":     "red",
        "強い売い": "bold red",
        "強い売り": "bold red",
    }

    def colored_score(s: float) -> str:
        if s >= 70: return f"[bold green]{s:.1f}[/bold green]"
        if s >= 55: return f"[green]{s:.1f}[/green]"
        if s >= 45: return f"[yellow]{s:.1f}[/yellow]"
        return f"[red]{s:.1f}[/red]"

    # ランキングテーブル
    table = Table(
        title=f"📊  6ヶ月後 株価上昇予測ランキング  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        show_lines=True,
    )
    table.add_column("順位",     style="bold white", justify="center", width=5)
    table.add_column("銘柄",     style="bold cyan",  width=6)
    table.add_column("企業名",                       width=24)
    table.add_column("現在株価", justify="right",    width=10)
    table.add_column("総合スコア", justify="center", width=10)
    table.add_column("推奨",     justify="center",   width=10)
    table.add_column("FA",       justify="center",   width=6)
    table.add_column("TA",       justify="center",   width=6)
    table.add_column("セン",     justify="center",   width=6)
    table.add_column("マク",     justify="center",   width=6)

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}

    for rank, a in enumerate(valid, 1):
        scores = {r.key: r.score for r in a.agent_results}
        style  = rec_styles.get(a.recommendation, "white")
        table.add_row(
            medals.get(rank, f"#{rank}"),
            a.ticker,
            a.company_name[:24],
            f"${a.current_price:.2f}",
            colored_score(a.final_score),
            f"[{style}]{a.recommendation}[/{style}]",
            colored_score(scores.get("fundamental", 50)),
            colored_score(scores.get("technical",   50)),
            colored_score(scores.get("sentiment",   50)),
            colored_score(scores.get("macro",       50)),
        )

    console.print()
    console.print(table)

    if errors:
        console.print(
            f"\n[yellow]⚠ 分析失敗: "
            f"{', '.join(f'{a.ticker}({a.error[:40]})' for a in errors)}[/yellow]"
        )

    # 上位3銘柄の詳細パネル
    console.print("\n[bold blue]━━━  上位銘柄 詳細分析  ━━━[/bold blue]\n")

    for a in valid[:3]:
        style = rec_styles.get(a.recommendation, "white")
        content = (
            f"[bold]スコア: {a.final_score:.1f}/100  "
            f"推奨: [{style}]{a.recommendation}[/{style}]  "
            f"セクター: {a.sector}[/bold]\n\n"
        )
        if a.summary:
            content += f"[italic]{a.summary}[/italic]\n\n"

        content += "[bold underline]エージェント別スコア:[/bold underline]\n"
        for r in a.agent_results:
            s = "green" if r.score >= 65 else "yellow" if r.score >= 45 else "red"
            content += f"\n[bold]{r.name}[/bold]: [{s}]{r.score:.0f}/100[/{s}]  信頼度: {r.confidence}\n"
            for sig in r.signals[:3]:
                content += f"  ▸ {sig}\n"

        console.print(Panel(
            content.strip(),
            title=f"[bold cyan]{a.ticker}  {a.company_name}[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        ))

    # 免責事項
    console.print(Panel(
        "⚠️  [bold yellow]免責事項[/bold yellow]\n"
        "この分析は情報提供のみを目的としており、投資勧誘ではありません。\n"
        "AIによる予測には不確実性が伴います。投資は必ず自己責任で行ってください。\n"
        "過去データや現在の指標は将来の結果を保証するものではありません。",
        border_style="yellow",
        style="dim",
    ))


# ==============================================================================
# デフォルト銘柄リスト / エントリーポイント
# ==============================================================================

DEFAULT_TICKERS = [
    "NVDA",   # NVIDIA — AI/GPU
    "MSFT",   # Microsoft
    "AAPL",   # Apple
    "AMZN",   # Amazon
    "GOOGL",  # Alphabet
    "META",   # Meta
    "TSLA",   # Tesla
    "AMD",    # AMD
    "PLTR",   # Palantir
    "SMCI",   # Super Micro Computer
]


async def async_main():
    console.print(Panel.fit(
        "[bold blue]📈  株価予測マルチエージェントシステム[/bold blue]\n\n"
        "[dim]ファンダメンタル / テクニカル / センチメント / マクロの\n"
        "4専門エージェント + オーケストレーターが\n"
        "6ヶ月後に株価が上がりそうな銘柄を予測します[/dim]",
        border_style="blue",
        padding=(1, 3),
    ))

    tickers = (
        [t.upper() for t in sys.argv[1:]]
        if len(sys.argv) > 1
        else DEFAULT_TICKERS
    )

    if tickers == DEFAULT_TICKERS:
        console.print(f"\n[dim]📋 分析対象（デフォルト）: {', '.join(tickers)}[/dim]")
        console.print("[dim]💡 別の銘柄: python stock_predictor.py TICKER1 TICKER2 ...[/dim]\n")
    else:
        console.print(f"\n[dim]📋 分析対象: {', '.join(tickers)}[/dim]\n")

    async_client = anthropic.AsyncAnthropic()

    # 同時分析数を制限（API負荷対策）
    semaphore = asyncio.Semaphore(3)
    progress_tasks: dict[str, int] = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=False,
    ) as progress:
        for t in tickers:
            tid = progress.add_task(f"[dim]{t} 待機中...", total=None)
            progress_tasks[t] = tid

        async def run(ticker: str) -> StockAnalysis:
            async with semaphore:
                tid = progress_tasks[ticker]
                progress.update(tid, description=f"[cyan]{ticker}  4エージェント分析中...")
                result = await analyze_stock(async_client, ticker)
                if result.error:
                    progress.update(tid, description=f"[red]✗ {ticker}: {result.error[:50]}")
                else:
                    progress.update(
                        tid,
                        description=(
                            f"[green]✓ {ticker}  "
                            f"スコア: {result.final_score:.1f}  ({result.recommendation})"
                        ),
                    )
                return result

        analyses = await asyncio.gather(*[run(t) for t in tickers])

    display_results(list(analyses))


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print("[bold red]エラー: ANTHROPIC_API_KEY 環境変数が設定されていません[/bold red]")
        sys.exit(1)
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
