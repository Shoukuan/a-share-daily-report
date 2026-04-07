
"""
DataFetcher mixin submodule - 大宗交易数据
"""

from utils import get_logger
from datetime import datetime

logger = get_logger('data_fetcher')


class BlockTradeFetcherMixin:
    def get_block_trades(self, trade_date=None):
        """
        获取大宗交易数据（当日TOP10）
        返回列表：[{
            "code": str,        # 股票代码
            "name": str,        # 股票名称
            "price": float,     # 成交价
            "volume": int,      # 成交量（手）
            "amount": float,    # 成交额（元）
            "discount": float,  # 折溢价率（%）
            "buyer": str,       # 买方营业部
            "seller": str       # 卖方营业部
        }, ...]
        """
        if self._akshare_unavailable:
            return {"success": False, "error": "akshare 不可用", "data": None}

        if not self.ak:
            return {"success": False, "error": "akshare 不可用", "data": None}

        try:
            # 构造日期参数
            if trade_date is None:
                date_str = datetime.now().strftime("%Y%m%d")
            else:
                # 统一转换为 YYYYMMDD 格式
                date_str = str(trade_date).replace("-", "")

            df = self.ak.stock_dzjy_mrtj(date=date_str)

            if df is None or (hasattr(df, 'empty') and df.empty):
                logger.warning(f"大宗交易数据为空: {date_str}")
                return {"success": True, "data": []}

            # 字段映射（akshare 可能返回不同字段名）
            col_map = {
                "code":     ["证券代码", "code", "stock_code", "ts_code"],
                "name":     ["证券简称", "name", "stock_name", "证券名称"],
                "price":    ["成交价", "price", "trade_price", "deal_price"],
                "volume":   ["成交量", "volume", "deal_volume", "成交量(手)"],
                "amount":   ["成交额", "amount", "deal_amount", "成交额(元)"],
                "discount": ["折溢价率", "discount", "premium_rate", "溢价率(%)"],
                "buyer":    ["买方营业部", "buyer", "buy_branch"],
                "seller":   ["卖方营业部", "seller", "sell_branch"],
            }

            def get_col_val(row, candidates, default):
                for col in candidates:
                    if col in row.index:
                        return row[col]
                return default

            records = []
            for _, row in df.iterrows():
                try:
                    record = {
                        "code":     str(get_col_val(row, col_map["code"], "")),
                        "name":     str(get_col_val(row, col_map["name"], "")),
                        "price":    float(get_col_val(row, col_map["price"], 0) or 0),
                        "volume":   int(float(get_col_val(row, col_map["volume"], 0) or 0)),
                        "amount":   float(get_col_val(row, col_map["amount"], 0) or 0),
                        "discount": float(get_col_val(row, col_map["discount"], 0) or 0),
                        "buyer":    str(get_col_val(row, col_map["buyer"], "")),
                        "seller":   str(get_col_val(row, col_map["seller"], "")),
                    }
                    records.append(record)
                except Exception as e:
                    logger.debug(f"大宗交易记录解析失败: {e}")
                    continue

            # 按成交额排序，取前10
            records.sort(key=lambda x: x["amount"], reverse=True)
            top10 = records[:10]

            logger.info(f"✅ 获取大宗交易数据成功: 共{len(records)}条，返回TOP{len(top10)}")
            return {"success": True, "data": top10}

        except Exception as e:
            import traceback
            logger.error(f"获取大宗交易数据失败: {e}\n{traceback.format_exc()}")
            return {"success": False, "error": str(e), "data": None}
