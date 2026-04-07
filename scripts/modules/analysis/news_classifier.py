"""
新闻分类和映射模块
提供新闻重要性分类、板块映射、个股映射和影响范围分类功能
"""

import os
import yaml

from utils import get_logger

logger = get_logger('news_classifier')


class NewsClassifier:
    """新闻分类器：根据重要性等级对新闻进行分类"""

    def __init__(self, config):
        """
        初始化新闻分类器

        Args:
            config: 配置字典
        """
        self.config = config
        logger.info("NewsClassifier 初始化完成")

    def classify_news(self, news_list):
        """
        根据重要性等级对新闻进行分类

        Args:
            news_list: 新闻列表，每项包含 importance 字段

        Returns:
            {
                "success": True,
                "data": [已分类的新闻列表，每项添加 level, level_icon, level_name]
            }
        """
        if not news_list:
            return {"success": True, "data": []}

        classified = []
        for news in news_list:
            importance = news.get('importance', 'medium')

            if importance == 'high':
                level = 'high'
                level_icon = "🔴"
                level_name = "重大影响"
            elif importance == 'medium':
                level = 'medium'
                level_icon = "🟡"
                level_name = "中等影响"
            else:
                level = 'low'
                level_icon = "🟢"
                level_name = "一般影响"

            news['level'] = level
            news['level_icon'] = level_icon
            news['level_name'] = level_name
            classified.append(news)

        return {"success": True, "data": classified}


class NewsMapper:
    """新闻映射引擎：新闻 → 板块 → 个股三级关联"""

    def __init__(self):
        """初始化新闻映射引擎"""
        self._init_sector_keywords()
        self._init_stock_name_map()
        self._init_impact_keywords()
        logger.info("NewsMapper 初始化完成")

    def map_news_to_sectors(self, news_list: list) -> dict:
        """
        将新闻列表映射到板块。

        Args:
            news_list: 新闻列表，每项含 title

        Returns:
            {
                "news_title": ["板块1", "板块2", ...],  # 每条新闻关联的板块
                ...
            }
        """
        if not news_list:
            return {}

        result = {}
        for news in news_list:
            title = news.get('title', '')
            if not title:
                continue

            matched_sectors = []
            for sector, keywords in self._sector_keywords.items():
                if any(keyword in title for keyword in keywords):
                    matched_sectors.append(sector)

            if matched_sectors:
                result[title] = matched_sectors

        return result

    def map_news_to_stocks(self, news_list: list, watchlist: list) -> dict:
        """
        将新闻列表映射到自选股。

        Args:
            news_list: 新闻列表
            watchlist: 自选股列表，每项含 name/code

        Returns:
            {
                "news_title": ["股票A", "股票B", ...],  # 每条新闻关联的自选股
                ...
            }
        """
        if not news_list or not watchlist:
            return {}

        # 动态构建股票名称映射表
        stock_names = []
        for stock in watchlist:
            name = stock.get('name', '')
            if name:
                stock_names.append(name)
                # 添加标准全名到映射表
                self._stock_name_map[name] = name

        # 扩展别名映射（支持简称）
        for full_name, aliases in self._stock_alias_map.items():
            for alias in aliases:
                if alias not in self._stock_name_map:
                    self._stock_name_map[alias] = full_name

        result = {}
        for news in news_list:
            title = news.get('title', '')
            if not title:
                continue

            matched_stocks = []
            for stock_name in stock_names:
                # 精确匹配或包含匹配
                if stock_name in title:
                    matched_stocks.append(stock_name)
                else:
                    # 检查别名
                    for alias, full_name in self._stock_alias_map.items():
                        if full_name == stock_name:
                            for a in self._stock_alias_map[full_name]:
                                if a in title:
                                    matched_stocks.append(stock_name)
                                    break

            if matched_stocks:
                result[title] = matched_stocks

        return result

    def classify_news_by_impact(self, news_list: list) -> dict:
        """
        根据新闻影响范围分类。

        Returns:
            {
                "market_wide": [news_title, ...],   # 市场级（影响所有股票）
                "sector_specific": [news_title, ...],  # 板块级（影响特定行业）
                "stock_specific": [news_title, ...],   # 个股级（影响单一股票）
            }
        """
        if not news_list:
            return {"market_wide": [], "sector_specific": [], "stock_specific": []}

        result = {
            "market_wide": [],
            "sector_specific": [],
            "stock_specific": []
        }

        # 首先映射到板块
        sector_mapping = self.map_news_to_sectors(news_list)

        for news in news_list:
            title = news.get('title', '')
            if not title:
                continue

            # 检查是否为市场级新闻
            if any(keyword in title for keyword in self._market_wide_keywords):
                result["market_wide"].append(title)
            # 检查是否为个股级新闻（包含股票名称）
            elif any(keyword in title for keyword in self._stock_specific_keywords):
                result["stock_specific"].append(title)
            # 否则视为板块级新闻
            elif title in sector_mapping and sector_mapping[title]:
                result["sector_specific"].append(title)
            else:
                # 默认归类为板块级（即使没有明确匹配到板块）
                result["sector_specific"].append(title)

        return result

    def _init_sector_keywords(self):
        """初始化板块关键词库（硬编码）"""
        self._sector_keywords = {
            "AI算力": ["算力", "芯片", "GPU", "服务器", "AI", "人工智能", "大模型"],
            "半导体": ["半导体", "芯片", "集成电路", "晶圆", "封测"],
            "新能源": ["新能源", "光伏", "风电", "锂电池", "储能"],
            "汽车": ["汽车", "整车", "新能源车", "智能驾驶", "自动驾驶"],
            "医药": ["医药", "医疗", "生物", "疫苗", "创新药"],
            "消费": ["消费", "白酒", "食品饮料", "家电", "旅游"],
            "地产": ["地产", "房地产", "物业管理", "建筑"],
            "金融": ["金融", "银行", "证券", "保险"],
            "军工": ["军工", "国防", "航天", "航空"],
            "传媒": ["传媒", "游戏", "影视", "广告"],
            "化工": ["化工", "新材料", "炼化", "农药"],
            "机械": ["机械", "工程机械", "重工", "装备"],
            "电力": ["电力", "电网", "发电", "供电"],
            "煤炭": ["煤炭", "煤电", "焦煤"],
            "钢铁": ["钢铁", "铁矿石", "特钢"],
            "有色金属": ["有色金属", "铜", "铝", "稀土", "锂矿"],
            "农业": ["农业", "种业", "农药", "化肥"],
            "通信": ["通信", "5G", "6G", "光通信"],
            "计算机": ["计算机", "软件", "云计算", "大数据"],
            "电子": ["电子", "元器件", "PCB", "显示屏"],
            "环保": ["环保", "污水处理", "固废", "节能"],
            "交运": ["交运", "物流", "航运", "航空运输"],
        }

    def _init_stock_name_map(self):
        """初始化股票名称映射（从 watchlist 动态构建）"""
        self._stock_name_map = {}  # {标准化名称: 原始名称}
        self._stock_alias_map = {    # 别名映射（处理简称）
            "贵州茅台": ["茅台"],
            "宁德时代": ["宁德"],
            "比亚迪": ["比亚迪", "BYD"],
            "中国平安": ["平安"],
            "招商银行": ["招行"],
            "五粮液": ["五粮液"],
            "工业富联": ["富士康", "鸿海精密"],
            "中芯国际": ["中芯"],
            "腾讯控股": ["腾讯"],
            "中国移动": ["中国移动"],
            "贵州茅台": ["茅台"],
        }

    def _init_impact_keywords(self):
        """初始化影响级别关键词"""
        # 市场级关键词：影响整体市场的政策、宏观事件
        self._market_wide_keywords = [
            "央行", "降准", "降息", "加息", "宏观", "经济数据",
            "GDP", "CPI", "PPI", "PMI", "贸易战", "国际关系",
            "股市", "A股", "沪深", "创业板", "科创板", "大盘",
            "人民币", "汇率", "通胀", "通缩", "财政政策",
            "货币政策", "流动性", "杠杆", "牛熊", "熔断",
        ]
        # 个股级关键词：明确提及具体公司或股票
        self._stock_specific_keywords = [
            "股份", "集团", "有限公司", "公司", "业绩", "财报",
            "涨停", "跌停", "停牌", "复牌", "重组", "并购",
            "增发", "配股", "分红", "派息", "回购", "减持",
            "增持", "董事长", "CEO", "董事会", "股东大会",
        ]