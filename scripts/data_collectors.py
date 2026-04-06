"""
数据采集器
通过基类复用早报/晚报公共采集逻辑。
"""

from errors import DataFetchError


class BaseDataCollector:
    def __init__(self, data_fetcher, analyzer, logger):
        self.data_fetcher = data_fetcher
        self.analyzer = analyzer
        self.logger = logger

    def _collect_core_indices(self, data, dt):
        self.logger.info("采集A股指数数据...")
        index_sh = self.data_fetcher.get_index_data("000001.SH", dt)
        index_sz = self.data_fetcher.get_index_data("399001.SZ", dt)
        index_cyb = self.data_fetcher.get_index_data("399006.SZ", dt)
        data["index_sh"] = index_sh
        data["index_sz"] = index_sz
        data["index_cyb"] = index_cyb
        return {
            "000001.SH": index_sh,
            "399001.SZ": index_sz,
            "399006.SZ": index_cyb,
        }

    def _collect_common_market(self, data, dt, index_cache, *, include_major_indices=False):
        if include_major_indices:
            self.logger.info("采集主要指数数据...")
            data["major_indices"] = self.data_fetcher.get_major_indices(dt)

        self.logger.info("采集市场情绪数据...")
        data["sentiment"] = self.data_fetcher.get_market_sentiment(dt, index_cache=index_cache)

        self.logger.info("采集资金流向数据（北向/主力）...")
        data["money_flow"] = self.data_fetcher.get_money_flow(dt)

        self.logger.info("采集行业资金流向...")
        data["industry_fund_flow"] = self.data_fetcher.get_industry_fund_flow(dt)

        self.logger.info("采集新闻数据...")
        data["news"] = self.data_fetcher.get_news(dt, limit=10)

        self.logger.info("获取自选股表现...")
        watchlist = self.analyzer.watchlist
        perf_result = self.data_fetcher.get_watchlist_performance(watchlist, dt)
        data["watchlist_performance"] = perf_result.get("data", []) if perf_result.get("success") else []

    def collect(self, dt):
        raise NotImplementedError


class MorningDataCollector(BaseDataCollector):
    def collect(self, dt):
        try:
            data = {}
            index_cache = self._collect_core_indices(data, dt)
            self._collect_common_market(data, dt, index_cache, include_major_indices=True)

            self.logger.info("采集美股数据...")
            data["us_market"] = self.data_fetcher.get_us_market()

            self.logger.info("采集期指数据...")
            data["futures"] = self.data_fetcher.get_futures_data()

            self.logger.info("采集国际事件数据...")
            data["international_events"] = self.data_fetcher.get_international_events(dt)
            return data
        except Exception as e:
            raise DataFetchError(f"morning data collect failed: {e}") from e


class EveningDataCollector(BaseDataCollector):
    def collect(self, dt):
        try:
            data = {}
            index_cache = self._collect_core_indices(data, dt)

            self.logger.info("采集市场全景数据...")
            data["market_overview"] = self.data_fetcher.get_market_overview(dt)

            self.logger.info("采集市场深度数据...")
            data["market_depth"] = self.data_fetcher.get_market_depth(dt)

            self.logger.info("采集主要指数数据...")
            data["major_indices"] = self.data_fetcher.get_major_indices(dt)

            self.logger.info("采集全球资产数据...")
            data["global_assets"] = self.data_fetcher.get_global_assets()

            self._collect_common_market(data, dt, index_cache, include_major_indices=False)

            self.logger.info("采集板块数据...")
            data["sectors"] = self.data_fetcher.get_sector_data(dt)

            self.logger.info("采集龙虎榜数据...")
            data["lhb"] = self.data_fetcher.get_lhb_data(dt)
            return data
        except Exception as e:
            raise DataFetchError(f"evening data collect failed: {e}") from e
