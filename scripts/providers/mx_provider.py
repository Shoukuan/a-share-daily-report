"""
mx-data provider
封装请求、重试与常用解析逻辑。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional


class MXDataProvider:
    def __init__(
        self,
        logger,
        get_apikey: Callable[[], str],
        handle_status: Callable[[int, str], bool],
        post_json_with_retry: Callable[..., Any],
        retry_policy: Dict[str, Any],
    ):
        self.logger = logger
        self._get_apikey = get_apikey
        self._handle_status = handle_status
        self._post_json_with_retry = post_json_with_retry
        self._retry_policy = retry_policy

    def query_json(self, tool_query: str, timeout_sec: int) -> Dict[str, Any]:
        """
        调用 mx-data claw/query 并自动处理 status=113 的备用 key 重试。
        返回 raw json（status 必为0），否则抛异常。
        """
        cur_key = self._get_apikey()
        if not cur_key:
            raise ValueError("MX_APIKEY 未设置")

        def _do_query(api_key: str) -> Dict[str, Any]:
            resp = self._post_json_with_retry(
                url="https://mkapi2.dfcfs.com/finskillshub/api/claw/query",
                payload={"toolQuery": tool_query},
                headers={"Content-Type": "application/json", "apikey": api_key},
                timeout=timeout_sec,
                retries=self._retry_policy["http_retries"],
                backoff_seconds=self._retry_policy["http_backoff_seconds"],
            )
            if resp.status_code != 200:
                raise RuntimeError(f"mx-data http status={resp.status_code}")
            return resp.json()

        raw = _do_query(cur_key)
        api_status = int(raw.get("status", 0) or 0)
        if api_status == 0:
            return raw

        should_retry = self._handle_status(api_status, str(raw.get("message", "")))
        if should_retry:
            retry_key = self._get_apikey()
            if retry_key and retry_key != cur_key:
                self.logger.info("mx-data 使用备用key重试 query")
                raw = _do_query(retry_key)
                api_status = int(raw.get("status", 0) or 0)
                if api_status == 0:
                    return raw
                raise RuntimeError(
                    f"mx-data 备用key也失败 status={api_status}: {raw.get('message', '')}"
                )
            raise RuntimeError("mx-data 无可用备用key，放弃")

        raise RuntimeError(f"mx-data API error status={api_status}: {raw.get('message', '')}")

    def extract_tables(self, raw: Dict[str, Any]) -> list:
        """从 mx-data 返回中提取 dataTableDTOList。"""
        outer = raw.get("data") or {}
        if not isinstance(outer, dict):
            return []
        inner = outer.get("data") or {}
        if not isinstance(inner, dict):
            return []

        search_dto = inner.get("searchDataResultDTO", inner)
        tables = search_dto.get("dataTableDTOList", [])
        if not tables:
            tables = inner.get("dataTableDTOList", []) or raw.get("dataTableDTOList", [])
        return tables if isinstance(tables, list) else []

    def parse_watchlist_row(self, raw: Dict[str, Any]) -> Dict[str, float]:
        """解析单只自选股 mx-data 返回。"""
        tables = self.extract_tables(raw)
        row: Dict[str, float] = {}

        for tbl in tables:
            name_map = tbl.get("nameMap", {})
            table_data = tbl.get("table", {})
            if not isinstance(name_map, dict) or not isinstance(table_data, dict):
                continue

            for fid, fname in name_map.items():
                vals = table_data.get(fid, [None])
                v = vals[0] if vals else None
                if v is None:
                    continue

                fn = str(fname)
                try:
                    v_float = float(str(v).replace("%", "").strip())
                except (ValueError, TypeError):
                    continue

                if "最新价" in fn or "收盘" in fn:
                    row["price"] = v_float
                elif "涨跌幅" in fn:
                    row["change_pct"] = v_float
                elif "成交额" in fn:
                    row["amount"] = v_float
                elif "振幅" in fn:
                    row["amplitude"] = v_float
                elif "换手率" in fn:
                    row["turnover"] = v_float
                elif "量比" in fn:
                    row["volume_ratio"] = v_float
                elif "5日" in fn and ("均线" in fn or "MA" in fn.upper()):
                    row["ma5"] = v_float
                elif "20日" in fn and ("均线" in fn or "MA" in fn.upper()):
                    row["ma20"] = v_float

        return row

    def parse_futures(
        self,
        raw: Dict[str, Any],
        build_impact_text: Callable[[float, str], str],
        target_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        解析 mx-data 期指响应。
        target_key: 'CSI300' 或 'A50'，如果传入则只返回对应 key。
        """
        futures_data = {"futures": {}}
        tables = self.extract_tables(raw)

        for table in tables:
            title = str(table.get("title", "")).lower()
            entity_name = str(table.get("entityName", "")).lower()
            name_map = table.get("nameMap", {})
            table_data = table.get("table", {})
            if not isinstance(name_map, dict) or not isinstance(table_data, dict):
                continue

            change_pct = 0.0
            for field_id, field_name in name_map.items():
                if field_name != "涨跌幅":
                    continue
                values = table_data.get(field_id, [])
                if values and values[0] not in ["-", "", None]:
                    try:
                        change_pct = float(str(values[0]).strip().rstrip("%"))
                    except (ValueError, TypeError):
                        change_pct = 0.0
                break

            future_key = None
            if "a50" in title or "a50" in entity_name:
                future_key = "A50"
            elif (
                "沪深300" in title
                or "沪深300" in entity_name
                or "hs300" in title
                or "csi300" in title
            ):
                future_key = "CSI300"

            if not future_key:
                continue
            if target_key and future_key != target_key:
                continue

            is_realtime = any(str(k).startswith("f") for k in name_map.keys())
            if future_key in futures_data["futures"] and not is_realtime:
                continue

            futures_data["futures"][future_key] = {
                "name": "A50期指" if future_key == "A50" else "沪深300期指",
                "code": "CFF_RE_IF",
                "change_pct": change_pct,
                "is_realtime": is_realtime,
                "impact": build_impact_text(
                    change_pct, "A50" if future_key == "A50" else "沪深300"
                ),
            }

        if target_key and target_key not in futures_data["futures"]:
            return {}
        return futures_data

    def parse_industry_fund_flow(self, raw: Dict[str, Any], update_time: str) -> Dict[str, Any]:
        """解析行业资金流（mx-data）为统一结构。"""
        tables = self.extract_tables(raw)
        if not tables:
            raise ValueError("mx-data 未返回行业资金流数据")

        inflow_top5 = []
        outflow_top5 = []
        all_rows = []

        for tbl in tables:
            name_map = tbl.get("nameMap", {})
            table_data = tbl.get("table", {})
            if not isinstance(name_map, dict) or not isinstance(table_data, dict):
                continue

            col_to_id = {str(fname): fid for fid, fname in name_map.items()}
            rank_id = col_to_id.get("排名")
            net_id = col_to_id.get("今日主力净流入-净额")
            if not rank_id or not net_id:
                continue

            rank_vals = table_data.get(rank_id, [])
            if not rank_vals:
                continue

            rows = []
            id_keys = [fid for fid in table_data if fid in name_map]
            if not id_keys:
                continue
            num_rows = max(len(table_data.get(fid, [])) for fid in id_keys)

            mapping = {
                "rank": "排名",
                "industry_name": "名称",
                "net_inflow": "今日主力净流入-净额",
                "change_pct": "今日涨跌幅",
                "leading_stock": "今日主力净流入最大股",
            }
            for i in range(num_rows):
                row = {}
                for py_name, cn_name in mapping.items():
                    fid = col_to_id.get(cn_name)
                    if not fid or fid not in table_data:
                        continue
                    vals = table_data[fid]
                    if i < len(vals) and vals[i] not in ["-", "", None]:
                        row[py_name] = vals[i]
                if "rank" not in row:
                    continue
                try:
                    int(row["rank"])
                except (ValueError, TypeError):
                    continue
                try:
                    row["net_inflow_val"] = float(row.get("net_inflow", 0))
                except (ValueError, TypeError):
                    row["net_inflow_val"] = 0.0
                rows.append(row)

            all_rows.extend(rows)

        all_rows.sort(key=lambda x: x.get("net_inflow_val", 0), reverse=True)

        for idx, r in enumerate(all_rows):
            entry = {
                "rank": idx + 1,
                "industry": str(r.get("industry_name", "")),
                "net_inflow": r.get("net_inflow_val", 0),
                "leading_stock": str(r.get("leading_stock", "")),
            }
            if "change_pct" in r:
                try:
                    entry["leading_stock_change"] = float(r["change_pct"])
                except (ValueError, TypeError):
                    entry["leading_stock_change"] = 0

            if r.get("net_inflow_val", 0) > 0:
                if len(inflow_top5) < 5:
                    entry["rank"] = len(inflow_top5) + 1
                    inflow_top5.append(entry)
            elif len(outflow_top5) < 5:
                outflow_top5.append(entry)

        outflow_top5.reverse()
        for idx, item in enumerate(outflow_top5):
            item["rank"] = idx + 1

        return {
            "update_time": update_time,
            "total_industries": len(all_rows),
            "top_net_inflow": inflow_top5,
            "top_net_outflow": outflow_top5,
        }
