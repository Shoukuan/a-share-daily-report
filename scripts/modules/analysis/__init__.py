"""
Analysis modules package
"""

# Import only existing modules to avoid import errors
# The __all__ list defines what should be available once all modules are created

__all__ = [
    'SummaryGenerator',
    'WatchlistAnalyzer',
    'TechnicalIndicators',
    'PositionSizer',
    'ComprehensiveAnalyzer',
    'MarketOverview',
    'NewsClassifier',
    'NewsMapper',
]

# Conditional imports to avoid errors when modules don't exist yet
try:
    from .summary_generator import SummaryGenerator
except ImportError:
    pass

try:
    from .watchlist_analyzer import WatchlistAnalyzer
except ImportError:
    pass

try:
    from .technical_indicators import TechnicalIndicators
except ImportError:
    pass

try:
    from .position_sizer import PositionSizer
except ImportError:
    pass

try:
    from .market_overview import MarketOverview
except ImportError:
    pass

try:
    from .news_classifier import NewsClassifier, NewsMapper
except ImportError:
    pass

try:
    from .comprehensive_analyzer import ComprehensiveAnalyzer
except ImportError:
    pass