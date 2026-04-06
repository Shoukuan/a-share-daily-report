"""
国际事件查询补丁 — 插入到 data_fetcher.py 的 get_major_indices 方法之前
"""

# 该文件是历史补丁片段，不参与运行；保留为参考，避免语法检查报错。
if False:

    def get_international_events(self, dt=None):
        """
        获取昨夜今晨国际事件（可能影响 A股）
        数据源：mx-search 查询国际财经事件 + 美股/大宗商品联动
        缓存 ttl=6h（早报生成后半天有效）
        """
        if dt is None:
            dt = datetime.now()
        date_str = format_date(dt, '%Y-%m-%d')
        cache_key = f'international_events_{date_str}'
        cached = get_cache(cache_key, namespace='mx_search', ttl=21600)
        if cached is not None:
            return {"success": True, "data": cached, "source": "cache", "cached": True}

        events = []

        # ── 1. mx-search 查询昨夜国际财经事件 ──
        self._load_env()
        mx_apikey = os.getenv('MX_APIKEY')
        if mx_apikey:
            try:
                import json
                import urllib.request

                prev_dt = parse_date(date_str) - timedelta(days=1)
                prev_str = format_date(prev_dt, '%Y-%m-%d')
                query = f"昨夜今晨国际事件 {prev_str} 中美 中东 美联储 原油 黄金"
                payload = json.dumps({"toolQuery": query}).encode('utf-8')
                req = urllib.request.Request(
                    'https://mkapi2.dfcfs.com/finskillshub/api/claw/query',
                    data=payload, headers={'Content-Type': 'application/json', 'apikey': mx_apikey},
                    method='POST'
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    raw = json.loads(resp.read().decode('utf-8'))

                api_status = raw.get('status', 0)
                if api_status == 113:
                    self._mx_key_exhausted = True
                    backup = os.getenv('MX_APIKEY_BACKUP', '')
                    if backup:
                        req2 = urllib.request.Request(
                            'https://mkapi2.dfcfs.com/finskillshub/api/claw/query',
                            data=payload, headers={'Content-Type': 'application/json', 'apikey': backup},
                            method='POST'
                        )
                        with urllib.request.urlopen(req2, timeout=15) as resp2:
                            raw = json.loads(resp2.read().decode('utf-8'))
                        api_status = raw.get('status', 0)

                if api_status == 0:
                    outer = raw.get('data') or {}
                    inner = outer.get('data') or {}
                    search_dto = inner.get('searchDataResultDTO', {})
                    tables = search_dto.get('dataTableDTOList', [])

                    for tbl in tables:
                        name_map = tbl.get('nameMap', {})
                        table_data = tbl.get('table', {})
                        entity_name = tbl.get('entityName', '') or tbl.get('title', '')
                        for fid, fname in name_map.items():
                            if str(fname) in ('事件', '新闻', '标题', '内容', 'description', 'title'):
                                vals = table_data.get(fid, [])
                                for v in vals:
                                    if v and str(v) not in ['-', '', 'None'] and len(str(v)) > 15:
                                        text = str(v)
                                        category = self._classify_event_category(text)
                                        events.append({
                                            "title": text[:60],
                                            "description": text[:200],
                                            "category": category,
                                            "impact_level": self._judge_impact_level(text),
                                            "a_share_impact": self._generate_a_share_impact(text),
                                            "affected_sectors": self._get_affected_sectors(text),
                                            "source": "妙想财经",
                                            "url": ""
                                        })
            except Exception as e:
                logger.warning(f"mx-search 国际事件查询失败: {e}")

        # ── 2. 自动补充：美股指数大幅波动 ──
        us_result = self.get_us_market()
        if us_result.get('success'):
            us_data = us_result.get('data', {})
            for name, info in us_data.get('indices', {}).items():
                label = {"nasdaq": "纳斯达克", "sp500": "标普500", "dow": "道琼斯"}.get(name, name)
                chg = info.get('change_pct', 0)
                if abs(chg) > 0.5:
                    events.append({
                        "title": f"{label}{'大涨' if chg > 0 else '大跌'}{abs(chg):.2f}%",
                        "description": f"{info.get('name', label)} 收盘 {info.get('close', 0):.0f} 点，{chg:+.2f}%",
                        "category": "海外股市",
                        "impact_level": "high" if abs(chg) > 1.5 else "medium",
                        "a_share_impact": f"{'上涨提振A股开盘情绪' if chg > 0 else '下跌可能传染A股低开，外资或减仓'}",
                        "affected_sectors": self._get_a_share_impact_sectors(name, chg),
                        "source": "yfinance",
                        "url": ""
                    })

        # ── 3. 自动补充：中概股/港股重要表现 ──
        if us_result.get('success'):
            us_data = us_result.get('data', {})
            cdc = us_data.get('chinadotcom', {})
            for name, info in cdc.items():
                chg = info.get('change_pct', 0)
                if abs(chg) > 2:
                    display = info.get('name', name).replace('Group Holding Limited', '').replace('Holdings Inc.', '').strip()
                    events.append({
                        "title": f"{display}{'大涨' if chg > 0 else '大跌'}{abs(chg):.2f}%",
                        "description": f"收盘 {chg:+.2f}%，可能传导至A股相关板块",
                        "category": "中概股",
                        "impact_level": "medium",
                        "a_share_impact": "可能传导至A股科技/互联网/新能源等同概念板块",
                        "affected_sectors": ["科技", "互联网"] if chg > 0 else ["科技", "互联网"],
                        "source": "yfinance",
                        "url": ""
                    })

        # ── 4. 期指异动 ──
        futures_result = self.get_futures_data()
        if futures_result.get('success'):
            fut = futures_result.get('data', {})
            for key, fi in fut.get('futures', {}).items():
                chg = fi.get('change_pct', 0)
                if abs(chg) > 0.5:
                    events.append({
                        "title": f"{fi.get('name', key)}期指{chg:+.2f}%",
                        "description": f"{fi.get('impact', '')}",
                        "category": "期货市场",
                        "impact_level": "high" if abs(chg) > 1 else "medium",
                        "a_share_impact": fi.get('impact', ''),
                        "affected_sectors": ["大盘蓝筹"] if "A50" in key else ["权重股"],
                        "source": "mx-data",
                        "url": ""
                    })

        if events:
            set_cache(cache_key, events, namespace='mx_search', ttl=21600)
            logger.info(f"✅ 国际事件获取成功: {len(events)} 条")
            return {"success": True, "data": events, "source": "combined", "cached": False}
        else:
            logger.info("昨夜今晨暂无重大国际事件")
            return {"success": True, "data": [], "source": "none", "cached": False}

    def _classify_event_category(self, text):
        """根据事件文本自动分类"""
        t = text.lower()
        if any(k in t for k in ['石油', '原油', 'oil', 'opec', '能源', '油价']):
            return "能源"
        elif any(k in t for k in ['贸易', '关税', 'tariff', '制裁', '制裁', 'wto']):
            return "贸易战"
        elif any(k in t for k in ['美联储', 'fed', '利率', '加息', '降息', '通胀', 'cpi', 'fomc']):
            return "货币政策"
        elif any(k in t for k in ['战争', '冲突', '导弹', '军事', '海峡', '制裁']):
            return "地缘政治"
        elif any(k in t for k in ['科技', '芯片', '半导体', 'huawei', '华为', '制裁']):
            return "科技制裁"
        elif any(k in t for k in ['黄金', 'gold', '贵金属']):
            return "大宗商品"
        elif any(k in t for k in ['汇率', 'dollar', '美元', '人民币', 'rmb', 'forex', '汇率']):
            return "汇率"
        else:
            return "宏观经济"

    def _judge_impact_level(self, text):
        """判断事件影响等级"""
        t = text.lower()
        high_words = ['战', '危机', '暴涨', '暴跌', '制裁', '冲突', '紧急', '崩盘', '暴雷']
        if any(w in t for w in high_words):
            return "high"
        return "medium"

    def _generate_a_share_impact(self, text):
        """根据事件文本生成对 A股的影响说明"""
        t = text.lower()
        if any(k in t for k in ['石油', '原油', 'oil', '油价']):
            if any(w in t for w in ['涨', '升', '飙升']):
                return "油价上涨推升输入性通胀压力，不利航空/化工/物流等成本敏感行业，利好石油开采/新能源替代板块"
            else:
                return "油价下跌利好航空物流降成本，利空石油开采板块"
        elif any(k in t for k in ['关税', '贸易', '制裁']):
            return "贸易摩擦升级打压出口企业，国产替代/内需受益，出口链承压"
        elif any(k in t for k in ['美联储', 'fed', '加息']):
            return "美联储鹰派信号或加剧外资流出压力，人民币承压，北向资金可能减仓"
        elif any(k in t for k in ['降息', '宽松']):
            return "降息利好全球风险偏好，外资或回流新兴市场，A股获支撑"
        elif any(k in t for k in ['美元', 'dollar']):
            if any(w in t for w in ['涨', '强', '升']):
                return "美元走强压制新兴市场资产价格，人民币汇率承压，外资流出概率上升"
            else:
                return "美元走弱利好新兴市场资产流入"
        else:
            return "事件可能通过情绪面传导至A股市场，关注相关板块联动"

    def _get_affected_sectors(self, text):
        """根据事件文本提取受影响板块"""
        t = text.lower()
        sectors = []
        if any(k in t for k in ['石油', '原油', 'oil', '能源']):
            sectors += ['石油石化', '新能源', '航空', '化工', '物流']
        if any(k in t for k in ['贸易', '关税', '出口']):
            sectors += ['出口链', '外贸', '国产替代', '半导体']
        if any(k in t for k in ['半导体', '芯片', '科技', '华为']):
            sectors += ['半导体', '信创', '国产替代']
        if any(k in t for k in ['黄金', 'gold']):
            sectors += ['黄金', '贵金属']
        if any(k in t for k in ['美元', '汇率']):
            sectors += ['银行', '地产', '出口链']
        if any(k in t for k in ['美联储', '利率', '降息', '通胀']):
            sectors += ['大盘蓝筹', '券商']
        return sectors if sectors else ['大盘']

    def _get_a_share_impact_sectors(self, name, chg):
        """根据美股指数涨跌输出A股关联板块"""
        sectors = {"大盘", "大盘蓝筹"}
        if name == "nasdaq":
            sectors = ["科技", "半导体", "人工智能", "消费电子"]
        elif name == "sp500":
            sectors = ["大盘蓝筹", "消费", "医药"]
        elif name == "dow":
            sectors = ["金融", "工业", "能源"]
        return list(sectors)
