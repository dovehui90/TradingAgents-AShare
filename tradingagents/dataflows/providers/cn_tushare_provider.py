"""
CnTushareProvider — 基于 Tushare Pro 的 A 股资金数据 Provider
只实现 smart_money_analyst 需要的 8 个资金方法，其余方法不实现。
route_to_vendor 用 getattr 动态检测，未实现的方法自动 fallback 到 cn_akshare。
"""

import os
import logging
import pandas as pd
from .base import BaseMarketDataProvider

logger = logging.getLogger(__name__)

_DEFAULT_TUSHARE_TOKEN = "23651a8611b00bf491c7378d81d0bc6265543153530194be989e6ada"

_TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN") or _DEFAULT_TUSHARE_TOKEN

if not os.environ.get("TUSHARE_TOKEN"):
    logger.info("TUSHARE_TOKEN env not set, using built-in default token")
    # Set env so subprocesses and other modules can see it
    os.environ.setdefault("TUSHARE_TOKEN", _DEFAULT_TUSHARE_TOKEN)


def _get_pro():
    import tushare as ts
    ts.set_token(_TUSHARE_TOKEN)
    return ts.pro_api()


def _to_ts_code(symbol: str) -> str:
    """000001 → 000001.SZ, 600519.SH, 000001.SH 保持不变"""
    if "." in symbol:
        return symbol.upper()
    if symbol.startswith(("5", "6", "9")):
        return f"{symbol}.SH"
    return f"{symbol}.SZ"


class CnTushareProvider(BaseMarketDataProvider):
    """Tushare Pro 资金数据 provider，速度 0.08-0.13s/接口。"""

    @property
    def name(self) -> str:
        return "cn_tushare"

    # ── Abstract 方法 stub（交给 akshare fallback）──
    def get_stock_data(self, symbol, start_date, end_date):
        raise NotImplementedError("cn_tushare: use cn_akshare for stock_data")

    def get_indicators(self, symbol, indicator, curr_date, look_back_days):
        raise NotImplementedError("cn_tushare: use cn_akshare for indicators")

    def get_fundamentals(self, ticker, curr_date=None):
        raise NotImplementedError("cn_tushare: use cn_akshare for fundamentals")

    def get_balance_sheet(self, ticker, freq="quarterly", curr_date=None):
        raise NotImplementedError("cn_tushare: use cn_akshare for balance_sheet")

    def get_cashflow(self, ticker, freq="quarterly", curr_date=None):
        raise NotImplementedError("cn_tushare: use cn_akshare for cashflow")

    def get_income_statement(self, ticker, freq="quarterly", curr_date=None):
        raise NotImplementedError("cn_tushare: use cn_akshare for income_statement")

    def get_news(self, ticker, start_date, end_date):
        raise NotImplementedError("cn_tushare: use cn_akshare for news")

    def get_global_news(self, curr_date, look_back_days=7, limit=50):
        raise NotImplementedError("cn_tushare: use cn_akshare for global_news")

    def get_insider_transactions(self, symbol):
        raise NotImplementedError("cn_tushare: use cn_akshare for insider_transactions")

    # ── 以下 8 个方法供 smart_money_analyst 使用 ──

    def get_stock_data(self, symbol: str, start_date: str, end_date: str) -> str:
        """获取个股日线数据，走 Tushare pro.daily 接口。"""
        ts_code = _to_ts_code(symbol)
        sd = start_date.replace("-", "")
        ed = end_date.replace("-", "")
        pro = _get_pro()
        df = pro.daily(ts_code=ts_code, start_date=sd, end_date=ed)
        if df is None or df.empty:
            raise RuntimeError(f"Tushare: no daily data for {symbol} {start_date}~{end_date}")
        df = df.sort_values("trade_date")
        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
        # Convert to standard CSV format
        df = df.rename(columns={
            "trade_date": "Date", "open": "Open", "high": "High",
            "low": "Low", "close": "Close", "vol": "Volume", "amount": "Amount",
        })
        keep = [c for c in ["Date", "Open", "High", "Low", "Close", "Volume", "Amount"] if c in df.columns]
        return df[keep].to_csv(index=False)

    def get_f10_detail(self, symbol: str, category: int = 0) -> str:
        """F10 公司资料，通过 Tushare API 获取。
        category: 0=公司概况+财务摘要+股东+高管 2=财务分析 3=股东研究 4=主力追踪"""
        ts_code = _to_ts_code(symbol)
        pro = _get_pro()
        parts = []

        try:
            info = pro.stock_company(ts_code=ts_code)
            if info is not None and not info.empty:
                row = info.iloc[0]
                parts.append(f"[公司基本信息]\n名称: {row.get('com_name', '')}"
                    f"\n行业: {row.get('industry', '')}"
                    f"\n上市日期: {row.get('list_date', '')}"
                    f"\n注册资本: {row.get('reg_capital', '')}万"
                    f"\n主营业务: {row.get('business_scope', str(row.get('main_business', '')))}"
                )
        except Exception:
            pass

        if category in (0, 2):
            try:
                from datetime import datetime, timedelta
                end = datetime.now().strftime("%Y%m%d")
                start = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
                fin = pro.fina_indicator(ts_code=ts_code, start_date=start, end_date=end)
                if fin is not None and not fin.empty:
                    fin = fin.sort_values("end_date").tail(4)
                    cols = [c for c in ["end_date", "roe", "roa", "grossprofit_margin",
                        "netprofit_margin", "debt_to_assets", "current_ratio",
                        "eps", "bps", "or_yoy", "profit_yoy"] if c in fin.columns]
                    parts.append(f"[近4季财务指标]\n{fin[cols].to_string(index=False)}")
            except Exception:
                pass

        if category in (0, 3):
            try:
                holders = pro.top10_holders(ts_code=ts_code)
                if holders is not None and not holders.empty:
                    h = holders.sort_values("end_date").tail(10)
                    cols = [c for c in ["end_date", "holder_name", "hold_num", "hold_ratio"] if c in h.columns]
                    parts.append(f"[前十大股东]\n{h[cols].to_string(index=False)}")
            except Exception:
                pass

        if category in (0, 4):
            try:
                from datetime import datetime, timedelta
                end = datetime.now().strftime("%Y%m%d")
                start = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")
                trades = pro.stk_holdertrade(ts_code=ts_code, start_date=start, end_date=end)
                if trades is not None and not trades.empty:
                    t = trades.tail(10)
                    cols = [c for c in ["trade_date", "holder_name", "buy_vol", "sell_vol",
                        "vol_change", "hold_vol_after"] if c in t.columns]
                    parts.append(f"[股东增减持]\n{t[cols].to_string(index=False)}")
            except Exception:
                pass

        if parts:
            return f"## F10 公司资料（Tushare，category={category}）\n\n" + "\n\n".join(parts)
        raise NotImplementedError("Tushare F10: 数据暂不可用，回退到其他数据源")

    def get_individual_fund_flow(self, symbol: str) -> str:
        """个股近5日主力资金净流向，走 Tushare moneyflow 接口。"""
        from datetime import datetime, timedelta
        ts_code = _to_ts_code(symbol)
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
        pro = _get_pro()
        df = pro.moneyflow(ts_code=ts_code, start_date=start, end_date=end)
        if df is None or df.empty:
            return f"{symbol} 近期主力资金流向数据暂不可用。"
        df = df.sort_values("trade_date").tail(5).copy()
        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
        # 选取关键列并重命名
        cols = {"trade_date": "日期", "buy_sm_amount": "小单买入(万)", "sell_sm_amount": "小单卖出(万)",
                "buy_md_amount": "中单买入(万)", "sell_md_amount": "中单卖出(万)",
                "buy_lg_amount": "大单买入(万)", "sell_lg_amount": "大单卖出(万)",
                "buy_elg_amount": "超大单买入(万)", "sell_elg_amount": "超大单卖出(万)",
                "net_mf_amount": "净流入(万)"}
        keep = [c for c in cols if c in df.columns]
        df = df[keep].rename(columns={c: cols[c] for c in keep})
        return f"{symbol} 近5日主力资金净流向（Tushare）：\n{df.to_string(index=False)}"

    def get_individual_fund_flow_120d(self, symbol: str) -> str:
        """个股120日中长期资金趋势，走 Tushare moneyflow 接口。"""
        from datetime import datetime, timedelta
        ts_code = _to_ts_code(symbol)
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=150)).strftime("%Y%m%d")
        pro = _get_pro()
        df = pro.moneyflow(ts_code=ts_code, start_date=start, end_date=end)
        if df is None or df.empty:
            return f"{symbol} 120日资金流向数据暂不可用。"
        df = df.sort_values("trade_date").copy()
        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
        keep = [c for c in ["trade_date", "net_mf_amount"] if c in df.columns]
        df = df[keep]
        df.columns = [c.replace("trade_date", "日期").replace("net_mf_amount", "主力净流入(万)") for c in df.columns]
        return f"{symbol} 120日主力资金趋势（Tushare，{len(df)} 条）：\n{df.tail(30).to_string(index=False)}"

    def get_lhb_detail(self, symbol: str, date: str) -> str:
        """龙虎榜明细。"""
        ts_code = _to_ts_code(symbol)
        date_str = date.replace("-", "")
        pro = _get_pro()
        df = pro.top_list(trade_date=date_str)
        if df is None or df.empty:
            return f"{symbol} 在 {date} 无龙虎榜数据（非异动日属正常）。"
        df = df[df["ts_code"] == ts_code]
        if df.empty:
            return f"{symbol} 在 {date} 无龙虎榜数据（非异动日属正常）。"
        # 选取关键列
        keep = [c for c in ["trade_date", "ts_code", "name", "close", "pct_change",
                             "turnover_rate", "amount", "l_buy", "l_sell", "l_amount",
                             "net_amount", "net_rate", "reason"] if c in df.columns]
        df = df[keep]
        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
        return f"{symbol} 龙虎榜明细（{date}，Tushare）：\n{df.head(20).to_string(index=False)}"

    def get_hsgt_individual(self, symbol: str) -> str:
        """个股北向资金持仓 — 走 Tushare hk_hold 接口。"""
        from datetime import datetime, timedelta
        ts_code = _to_ts_code(symbol)
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
        pro = _get_pro()
        df = pro.hk_hold(ts_code=ts_code, start_date=start, end_date=end)
        if df is None or df.empty:
            return f"{symbol} 北向资金持仓数据暂不可用（可能非沪深港通标的）。"
        df = df.tail(5).copy()
        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
        cols = {"trade_date": "日期", "vol": "持股数(股)", "ratio": "占流通股比(%)"}
        keep = [c for c in cols if c in df.columns]
        df = df[keep].rename(columns={c: cols[c] for c in keep})
        return f"{symbol} 北向资金持仓（近5日，Tushare）：\n{df.to_string(index=False)}"

    def get_hsgt_flow(self) -> str:
        """北向资金整体净流入。"""
        from datetime import datetime, timedelta
        pro = _get_pro()
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
        df = pro.moneyflow_hsgt(start_date=start, end_date=end)
        if df is None or df.empty:
            raise NotImplementedError("tushare moneyflow_hsgt empty")
        df = df.tail(5).copy()
        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
        # 选取关键列
        keep = [c for c in ["trade_date", "north_money", "hgt", "sgt",
                             "south_money", "ggt_ss", "ggt_sz"] if c in df.columns]
        df = df[keep]
        df.columns = [c.replace("north_money", "北向合计").replace("hgt", "沪股通")
                       .replace("sgt", "深股通").replace("south_money", "南向合计")
                       .replace("ggt_ss", "港股通(沪)").replace("ggt_sz", "港股通(深)")
                       .replace("trade_date", "日期") for c in df.columns]
        return f"北向资金整体净流入（近5日，Tushare）：\n{df.to_string(index=False)}"

    def get_block_trades(self, symbol: str, start_date: str, end_date: str) -> str:
        """大宗交易明细。"""
        ts_code = _to_ts_code(symbol)
        sd = start_date.replace("-", "")
        ed = end_date.replace("-", "")
        pro = _get_pro()
        df = pro.block_trade(ts_code=ts_code, start_date=sd, end_date=ed)
        if df is None or df.empty:
            return f"{symbol} 在 {start_date}~{end_date} 无大宗交易数据。"
        df = df.copy()
        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
        return f"{symbol} 大宗交易明细（{start_date}~{end_date}，Tushare）：\n{df.tail(10).to_string(index=False)}"

    def get_lhb_institution_stats(self, symbol: str, start_date: str, end_date: str) -> str:
        """龙虎榜机构买卖统计。"""
        ts_code = _to_ts_code(symbol)
        sd = start_date.replace("-", "")
        ed = end_date.replace("-", "")
        pro = _get_pro()
        # 逐日获取 top_inst，过滤该股票
        from datetime import datetime, timedelta
        start_dt = datetime.strptime(sd, "%Y%m%d")
        end_dt = datetime.strptime(ed, "%Y%m%d")
        frames = []
        current = start_dt
        while current <= end_dt:
            day_str = current.strftime("%Y%m%d")
            try:
                df_day = pro.top_inst(trade_date=day_str)
                if df_day is not None and not df_day.empty:
                    df_day = df_day[df_day["ts_code"] == ts_code]
                    if not df_day.empty:
                        frames.append(df_day)
            except Exception:
                pass
            current += timedelta(days=1)
        if not frames:
            return f"{symbol} 在 {start_date}~{end_date} 无机构买卖统计数据。"
        combined = pd.concat(frames, ignore_index=True)
        if "trade_date" in combined.columns:
            combined["trade_date"] = pd.to_datetime(combined["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
        return f"{symbol} 龙虎榜机构买卖统计（{start_date}~{end_date}，Tushare）：\n{combined.to_string(index=False)}"

    def get_lhb_active_seats(self, start_date: str, end_date: str) -> str:
        """龙虎榜活跃营业部排行（市场级）。"""
        sd = start_date.replace("-", "")
        ed = end_date.replace("-", "")
        pro = _get_pro()
        # 逐日获取 top_inst 汇总
        from datetime import datetime, timedelta
        start_dt = datetime.strptime(sd, "%Y%m%d")
        end_dt = datetime.strptime(ed, "%Y%m%d")
        frames = []
        current = start_dt
        while current <= end_dt:
            day_str = current.strftime("%Y%m%d")
            try:
                df_day = pro.top_inst(trade_date=day_str)
                if df_day is not None and not df_day.empty:
                    frames.append(df_day)
            except Exception:
                pass
            current += timedelta(days=1)
        if not frames:
            return f"{start_date}~{end_date} 活跃营业部数据暂不可用。"
        combined = pd.concat(frames, ignore_index=True)
        # 按营业部汇总 net_buy
        if "exalter" in combined.columns and "net_buy" in combined.columns:
            grouped = combined.groupby("exalter").agg(
                total_net_buy=("net_buy", "sum"),
                trade_count=("trade_date", "count"),
            ).sort_values("total_net_buy", ascending=False).head(10)
            grouped = grouped.reset_index()
            return f"龙虎榜活跃营业部排行（{start_date}~{end_date}，Tushare，前10）：\n{grouped.to_string(index=False)}"
        return f"龙虎榜活跃营业部排行（{start_date}~{end_date}，Tushare）：\n{combined.head(10).to_string(index=False)}"

    def get_margin_detail(self, symbol: str, date: str) -> str:
        """个股融资融券明细。"""
        ts_code = _to_ts_code(symbol)
        date_str = date.replace("-", "")
        pro = _get_pro()
        df = pro.margin_detail(ts_code=ts_code, trade_date=date_str)
        if df is None or df.empty:
            return f"{symbol} 在 {date} 无融资融券记录。"
        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
        return f"{symbol} 融资融券明细（{date}，Tushare）：\n{df.head(5).to_string(index=False)}"
