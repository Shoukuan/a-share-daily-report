
"""
DataFetcher mixin submodule - 融资融券数据
"""

from utils import get_logger
from datetime import datetime

logger = get_logger('data_fetcher')


class MarginFetcherMixin:
    def get_margin_data(self, trade_date=None):
        """
        获取融资融券数据（全市场汇总）
        返回: {
            "rzye": float,      # 融资余额（元）
            "rzmre": float,     # 融资买入额（元）
            "rqye": float,      # 融券余额（元）
            "rqmcl": float,     # 融券卖出量（股）
            "rzrqye": float,    # 融资融券余额合计（元）
            "trade_date": str
        }
        """
        if self._akshare_unavailable:
            return {"success": False, "error": "akshare 不可用", "data": None}

        if not self.ak:
            return {"success": False, "error": "akshare 不可用", "data": None}

        try:
            # 获取上交所融资融券汇总数据
            df = self.ak.stock_margin_detail_sse()

            if df is None or (hasattr(df, 'empty') and df.empty):
                logger.warning("融资融券数据为空，尝试备用接口")
                df = self.ak.stock_margin_underlying_info_sse()

            if df is None or (hasattr(df, 'empty') and df.empty):
                logger.warning("融资融券数据获取为空")
                return {"success": False, "error": "融资融券数据为空", "data": None}

            # 尝试汇总各列
            col_map = {
                "rzye": ["融资余额", "rzye", "margin_balance"],
                "rzmre": ["融资买入额", "rzmre", "buy_amount"],
                "rqye": ["融券余额", "rqye", "short_balance"],
                "rqmcl": ["融券卖出量", "rqmcl", "sell_volume"],
                "rzrqye": ["融资融券余额", "rzrqye", "total_balance"],
            }

            result = {}
            for key, candidates in col_map.items():
                val = 0.0
                for col in candidates:
                    if col in df.columns:
                        try:
                            val = float(df[col].sum())
                        except Exception:
                            val = 0.0
                        break
                result[key] = val

            # 处理交易日期
            date_str = trade_date
            if date_str is None:
                date_cols = ["日期", "trade_date", "date", "数据日期"]
                for col in date_cols:
                    if col in df.columns:
                        try:
                            date_str = str(df[col].iloc[-1])
                        except Exception:
                            pass
                        break
            if date_str is None:
                date_str = datetime.now().strftime("%Y-%m-%d")

            result["trade_date"] = date_str

            logger.info(f"✅ 获取融资融券数据成功: 融资余额={result['rzye']/1e8:.2f}亿")
            return {"success": True, "data": result}

        except Exception as e:
            import traceback
            logger.error(f"获取融资融券数据失败: {e}\n{traceback.format_exc()}")
            return {"success": False, "error": str(e), "data": None}
