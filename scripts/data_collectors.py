"""
数据采集器
通过基类复用早报/晚报公共采集逻辑。
并行化：互相无依赖的数据源使用 ThreadPoolExecutor 并发拉取，
        有依赖关系的任务（如 get_market_sentiment 依赖 index_cache）仍串行执行。
"""

from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_EXCEPTION

from errors import DataFetchError


def _parallel_fetch(tasks, logger, timeout=60):
    """
    并行执行多个数据拉取任务。

    Args:
        tasks: dict[str, callable]  {key: callable}
        logger: 日志对象
        timeout: 并发等待总超时（秒）

    Returns:
        dict[str, Any]  {key: result}，失败的 key 对应值为 {"success": False, "error": str}
    """
    results = {}
    with ThreadPoolExecutor(max_workers=min(len(tasks), 8)) as executor:
        future_to_key = {executor.submit(fn): key for key, fn in tasks.items()}
        done, not_done = wait(future_to_key, timeout=timeout)

        for future in not_done:
            key = future_to_key[future]
            future.cancel()
            logger.warning(f"[parallel_fetch] {key} 超时，返回空结果")
            results[key] = {"success": False, "error": "timeout"}

        for future in done:
            key = future_to_key[future]
            try:
                results[key] = future.result()
            except Exception as e:
                logger.error(f"[parallel_fetch] {key} 失败: {e}")
                results[key] = {"success": False, "error": str(e)}

    return results


class BaseDataCollector:
    def __init__(self, data_fetcher, analyzer, logger):
        self.data_fetcher = data_fetcher
        self.analyzer = analyzer
        self.logger = logger

    def _collect_core_indices(self, data, dt):
        """并行拉取三大指数（互相独立）"""
        self.logger.info("并行采集A股三大指数...")
        tasks = {
            "000001.SH": lambda: self.data_fetcher.get_index_data("000001.SH", dt),
            "399001.SZ": lambda: self.data_fetcher.get_index_data("399001.SZ", dt),
            "399006.SZ": lambda: self.data_fetcher.get_index_data("399006.SZ", dt),
        }
        index_results = _parallel_fetch(tasks, self.logger, timeout=40)

        data["index_sh"] = index_results.get("000001.SH", {})
        data["index_sz"] = index_results.get("399001.SZ", {})
        data["index_cyb"] = index_results.get("399006.SZ", {})
        return {
            "000001.SH": index_results.get("000001.SH"),
            "399001.SZ": index_results.get("399001.SZ"),
            "399006.SZ": index_results.get("399006.SZ"),
        }

    def _collect_common_market(self, data, dt, index_cache, *, include_major_indices=False):
        """
        并行拉取公共市场数据。
        注意：get_market_sentiment 依赖 index_cache，需要 index_cache 完成后才能调用，
        但其自身不依赖本批次其他任务，可以和其他任务并行。
        """
        # 构建并行任务（所有任务互相独立）
        tasks = {
            "sentiment":         lambda: self.data_fetcher.get_market_sentiment(dt, index_cache=index_cache),
            "money_flow":        lambda: self.data_fetcher.get_money_flow(dt),
            "industry_fund_flow":lambda: self.data_fetcher.get_industry_fund_flow(dt),
            "news":              lambda: self.data_fetcher.get_news(dt, limit=10),
            "watchlist_perf":    lambda: self.data_fetcher.get_watchlist_performance(
                                    self.analyzer.watchlist, dt),
        }
        if include_major_indices:
            tasks["major_indices"] = lambda: self.data_fetcher.get_major_indices(dt)

        self.logger.info(f"并行采集公共市场数据（{len(tasks)} 个任务）...")
        results = _parallel_fetch(tasks, self.logger, timeout=90)

        data["sentiment"] = results.get("sentiment", {})
        data["money_flow"] = results.get("money_flow", {})
        data["industry_fund_flow"] = results.get("industry_fund_flow", {})
        data["news"] = results.get("news", {})

        perf_result = results.get("watchlist_perf", {})
        data["watchlist_performance"] = (
            perf_result.get("data", []) if perf_result.get("success") else []
        )

        if include_major_indices:
            data["major_indices"] = results.get("major_indices", {})

    def collect(self, dt):
        raise NotImplementedError


class MorningDataCollector(BaseDataCollector):
    def collect(self, dt):
        try:
            data = {}

            # 第一阶段：并行拉取三大指数（后续 sentiment 依赖其结果）
            index_cache = self._collect_core_indices(data, dt)

            # 第二阶段：并行拉取所有其余数据（8 个任务同时启动）
            self.logger.info("并行采集早报全部数据源...")
            tasks = {
                "sentiment":         lambda: self.data_fetcher.get_market_sentiment(dt, index_cache=index_cache),
                "money_flow":        lambda: self.data_fetcher.get_money_flow(dt),
                "industry_fund_flow":lambda: self.data_fetcher.get_industry_fund_flow(dt),
                "news":              lambda: self.data_fetcher.get_news(dt, limit=10),
                "watchlist_perf":    lambda: self.data_fetcher.get_watchlist_performance(
                                        self.analyzer.watchlist, dt),
                "major_indices":     lambda: self.data_fetcher.get_major_indices(dt),
                "us_market":         lambda: self.data_fetcher.get_us_market(),
                "futures":           lambda: self.data_fetcher.get_futures_data(),
                "international_events": lambda: self.data_fetcher.get_international_events(dt),
            }
            results = _parallel_fetch(tasks, self.logger, timeout=120)

            data["sentiment"] = results.get("sentiment", {})
            data["money_flow"] = results.get("money_flow", {})
            data["industry_fund_flow"] = results.get("industry_fund_flow", {})
            data["news"] = results.get("news", {})
            data["major_indices"] = results.get("major_indices", {})
            data["us_market"] = results.get("us_market", {})
            data["futures"] = results.get("futures", {})
            data["international_events"] = results.get("international_events", {})

            perf = results.get("watchlist_perf", {})
            data["watchlist_performance"] = perf.get("data", []) if perf.get("success") else []

            return data
        except Exception as e:
            raise DataFetchError(f"morning data collect failed: {e}") from e


class EveningDataCollector(BaseDataCollector):
    def collect(self, dt):
        try:
            data = {}

            # 第一阶段：并行拉取三大指数
            index_cache = self._collect_core_indices(data, dt)

            # 第二阶段：并行拉取所有其余数据（10 个任务同时启动）
            self.logger.info("并行采集晚报全部数据源...")
            tasks = {
                "market_overview":   lambda: self.data_fetcher.get_market_overview(dt),
                "market_depth":      lambda: self.data_fetcher.get_market_depth(dt),
                "major_indices":     lambda: self.data_fetcher.get_major_indices(dt),
                "global_assets":     lambda: self.data_fetcher.get_global_assets(),
                "sentiment":         lambda: self.data_fetcher.get_market_sentiment(dt, index_cache=index_cache),
                "money_flow":        lambda: self.data_fetcher.get_money_flow(dt),
                "industry_fund_flow":lambda: self.data_fetcher.get_industry_fund_flow(dt),
                "news":              lambda: self.data_fetcher.get_news(dt, limit=10),
                "watchlist_perf":    lambda: self.data_fetcher.get_watchlist_performance(
                                        self.analyzer.watchlist, dt),
                "sectors":           lambda: self.data_fetcher.get_sector_data(dt),
                "lhb":               lambda: self.data_fetcher.get_lhb_data(dt),
            }
            results = _parallel_fetch(tasks, self.logger, timeout=120)

            data["market_overview"] = results.get("market_overview", {})
            data["market_depth"] = results.get("market_depth", {})
            data["major_indices"] = results.get("major_indices", {})
            data["global_assets"] = results.get("global_assets", {})
            data["sentiment"] = results.get("sentiment", {})
            data["money_flow"] = results.get("money_flow", {})
            data["industry_fund_flow"] = results.get("industry_fund_flow", {})
            data["news"] = results.get("news", {})
            data["sectors"] = results.get("sectors", {})
            data["lhb"] = results.get("lhb", {})

            perf = results.get("watchlist_perf", {})
            data["watchlist_performance"] = perf.get("data", []) if perf.get("success") else []

            return data
        except Exception as e:
            raise DataFetchError(f"evening data collect failed: {e}") from e
