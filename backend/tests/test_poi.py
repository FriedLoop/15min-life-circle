"""设施分类与检索策略的单元测试。"""

from app.core import constants
from app.services.poi import classify_poi


def test_classify_prefers_school_over_pharmacy():
    """匹配顺序敏感：名称同时含『小学』与『药店』时应归为小学。

    FACILITY_CATEGORIES 中「小学」排在「药店」之前，
    若顺序被无意调整，这个用例会失败。
    """
    assert classify_poi("实验小学门口大参林药店") == "小学"


def test_classify_common_categories():
    assert classify_poi("大参林药店") == "药店"
    assert classify_poi("莞城中心菜市场") == "菜市场"
    assert classify_poi("中国农业银行莞城支行") == "银行"
    assert classify_poi("沙县小吃") == "餐饮"
    assert classify_poi("莞城社区卫生服务中心") == "医疗"
    assert classify_poi("阳光幼儿园") == "幼儿园"


def test_classify_unknown_falls_back_to_other():
    assert classify_poi("环球经贸中心") == "其他"


def test_poi_query_uses_dollar_union():
    """并集检索要求多个关键字以 $ 分隔。"""
    assert "$" in constants.POI_QUERY
    assert len(constants.POI_QUERY.split("$")) == len(constants.POI_QUERY_KEYWORDS)


def test_blindspot_categories_are_subset_of_defined():
    """判定盲区的类别必须已定义，否则检索时查不到数据。"""
    assert set(constants.BLINDSPOT_CATEGORIES).issubset(
        set(constants.FACILITY_CATEGORIES.keys())
    )


def test_page_size_within_baidu_limit():
    """百度地点检索单次最多返回 20 条。"""
    assert 1 <= constants.POI_PAGE_SIZE <= 20
    assert constants.POI_MAX_PAGES >= 1
