"""东方财富API服务类"""
import json
import asyncio
from typing import Optional, Dict, Any, Tuple
from astrbot.api import logger

try:
    import aiohttp
except ImportError:
    aiohttp = None


class EastMoneyAPIService:
    """东方财富API服务"""
    
    def __init__(self):
        self.session = None
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive'
        }
        
        # 常用股票代码映射
        self.code_id_dict = {
            '上证综指': '1.000001',
            '上证指数': '1.000001', 
            '深证成指': '0.399001',
            '深证指数': '0.399001',
            '创业板指': '0.399006',
            '创业板': '0.399006',
            '沪深300': '1.000300',
            '上证50': '1.000016',
            '科创50': '1.000688',
            '中小100': '0.399005',
            '中小板': '0.399005'
        }
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        if aiohttp is None:
            raise ImportError("需要安装aiohttp: pip install aiohttp")
        
        connector = aiohttp.TCPConnector(verify_ssl=False)
        timeout = aiohttp.ClientTimeout(total=30)
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers=self.headers
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if self.session:
            await self.session.close()
    
    async def get_code_id(self, code: str) -> Optional[Tuple[str, str]]:
        """
        获取东方财富股票专用的行情ID
        
        Args:
            code: 股票代码或简称
            
        Returns:
            (secid, name) 或 None
        """
        # 如果已经是完整的secid格式
        if '.' in code:
            return code, ''
        
        # 检查预定义映射
        if code in self.code_id_dict:
            return self.code_id_dict[code], code
        
        # 通过搜索API获取
        url = 'https://searchapi.eastmoney.com/api/suggest/get'
        params = {
            'input': code,
            'type': '14',
            'token': 'D43BF722C8E33BDC906FB84D85E326E8',
            'count': '10'  # 增加搜索结果数量，支持模糊搜索
        }
        
        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    text = await response.text()
                    data = json.loads(text)
                    
                    code_list = data.get('QuotationCodeTable', {}).get('Data', [])
                    if code_list:
                        # 排序：债券排到最后，股票优先
                        code_list.sort(
                            key=lambda x: x.get('SecurityTypeName') == '债券'
                        )
                        return code_list[0]['QuoteID'], code_list[0]['Name']
                        
        except Exception as e:
            logger.error(f"搜索股票代码失败 {code}: {e}")
        
        return None
    
    async def search_stocks_fuzzy(self, keyword: str) -> list:
        """
        模糊搜索股票，支持中文名称、拼音、代码等
        
        Args:
            keyword: 搜索关键词（中文名、拼音、代码等）
            
        Returns:
            股票候选列表，每个元素包含 {'code', 'name', 'market'}
        """
        # 先检查是否为有效的股票代码
        if keyword.isdigit() and len(keyword) == 6:
            from ..utils.validators import Validators
            if Validators.is_valid_stock_code(keyword):
                # 直接返回该股票
                stock_info = await self.get_stock_realtime_data(keyword)
                if stock_info:
                    return [{
                        'code': keyword,
                        'name': stock_info['name'],
                        'market': self._get_market_name(keyword)
                    }]
        
        # 通过搜索API进行模糊搜索
        url = 'https://searchapi.eastmoney.com/api/suggest/get'
        params = {
            'input': keyword,
            'type': '14',
            'token': 'D43BF722C8E33BDC906FB84D85E326E8',
            'count': '8'  # 返回8个候选结果
        }
        
        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    text = await response.text()
                    data = json.loads(text)
                    
                    code_list = data.get('QuotationCodeTable', {}).get('Data', [])
                    if not code_list:
                        return []
                    
                    # 过滤和整理结果
                    candidates = []
                    from ..utils.validators import Validators
                    
                    for item in code_list:
                        quote_id = item.get('QuoteID', '')
                        name = item.get('Name', '')
                        security_type = item.get('SecurityTypeName', '')
                        
                        # 提取纯代码（去掉市场前缀）
                        code = quote_id.split('.')[-1] if '.' in quote_id else quote_id
                        
                        # 只保留A股（排除债券、指数等）
                        if (code.isdigit() and len(code) == 6 and 
                            Validators.is_valid_stock_code(code) and
                            security_type != '债券'):
                            
                            candidates.append({
                                'code': code,
                                'name': name,
                                'market': self._get_market_name(code)
                            })
                    
                    # 去重并限制数量
                    seen_codes = set()
                    unique_candidates = []
                    for candidate in candidates:
                        if candidate['code'] not in seen_codes:
                            seen_codes.add(candidate['code'])
                            unique_candidates.append(candidate)
                            if len(unique_candidates) >= 5:  # 最多返回5个候选
                                break
                    
                    return unique_candidates
                    
        except Exception as e:
            logger.error(f"模糊搜索股票失败 {keyword}: {e}")
        
        return []
    
    def _get_market_name(self, code: str) -> str:
        """获取市场名称"""
        if code.startswith(('60', '68')):
            return '沪市'
        elif code.startswith(('00', '30')):
            return '深市' if code.startswith('00') else '创业板'
        elif code.startswith(('43', '83', '87')):
            return '北交所'
        else:
            return '未知'
    
    def _get_full_security_code(self, code: str) -> str:
        """
        获取完整的证券代码
        """
        if '.' not in code:
            # 根据代码前缀判断市场
            if code.startswith(('00', '30', '39')):  # 深市
                return f"0.{code}"
            elif code.startswith(('60', '68', '51')):  # 沪市
                return f"1.{code}"
            elif code.startswith(('43', '83', '87')):  # 北交所
                return f"0.{code}"
        return code
    
    async def get_stock_realtime_data(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        获取股票实时数据
        使用东方财富个股接口
        
        Args:
            stock_code: 股票代码
            
        Returns:
            股票实时数据字典或None
        """
        try:
            # 获取secid
            code_result = await self.get_code_id(stock_code)
            if not code_result:
                logger.error(f"无法找到股票代码: {stock_code}")
                return None
            
            secid, stock_name = code_result
            secid = self._get_full_security_code(secid)
            
            # 构建请求参数 - 只获取模拟交易必需的数据
            url = 'https://push2.eastmoney.com/api/qt/stock/get'
            fields = [
                'f58',  # 股票名称
                'f57',  # 股票代码  
                'f43',  # 最新价(元)
                'f44',  # 最高价(元)
                'f45',  # 最低价(元)
                'f46',  # 开盘价(元)
                'f60',  # 昨收价(元)
                'f47',  # 成交量(手)
                'f48',  # 成交额(元)
                'f169', # 涨跌额(元)
                'f170', # 涨跌幅(%)
                'f51',  # 涨停价(元)
                'f52',  # 跌停价(元)
                'f86',  # 时间戳
            ]
            
            params = {
                'fields': ','.join(fields),
                'secid': secid
            }
            
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if data.get('data') is None:
                        logger.error(f"获取股票数据失败，可能股票不存在: {stock_code}")
                        return None
                    
                    raw_data = data['data']
                    
                    # 解析数据 - 只返回模拟交易必需的字段
                    # 注意：东方财富API返回的价格数据需要除以100，涨跌幅数据需要除以100
                    result = {
                        'code': stock_code,
                        'name': raw_data.get('f58', stock_name),
                        'current_price': float(raw_data.get('f43', 0) or 0) / 100,  # 价格除以100
                        'open_price': float(raw_data.get('f46', 0) or 0) / 100,      # 开盘价除以100
                        'close_price': float(raw_data.get('f60', 0) or 0) / 100,     # 昨收价除以100
                        'high_price': float(raw_data.get('f44', 0) or 0) / 100,      # 最高价除以100
                        'low_price': float(raw_data.get('f45', 0) or 0) / 100,       # 最低价除以100
                        'volume': int(raw_data.get('f47', 0) or 0),                  # 成交量（手）
                        'turnover': float(raw_data.get('f48', 0) or 0),              # 成交额（元）
                        'change_amount': float(raw_data.get('f169', 0) or 0) / 100,  # 涨跌额除以100
                        'change_percent': float(raw_data.get('f170', 0) or 0) / 100, # 涨跌幅除以100
                        'limit_up': float(raw_data.get('f51', 0) or 0) / 100,        # 涨停价除以100
                        'limit_down': float(raw_data.get('f52', 0) or 0) / 100,      # 跌停价除以100
                        'timestamp': raw_data.get('f86', ''),
                    }
                    
                    return result
                else:
                    logger.error(f"请求失败，状态码: {response.status}")
                    return None
                    
        except Exception as e:
            logger.error(f"获取股票实时数据失败 {stock_code}: {e}")
            return None
    
    async def batch_get_stocks_data(self, stock_codes: list) -> Dict[str, Dict[str, Any]]:
        """
        批量获取股票数据
        
        Args:
            stock_codes: 股票代码列表
            
        Returns:
            {stock_code: stock_data} 字典
        """
        results = {}
        
        # 创建并发任务
        tasks = []
        for code in stock_codes:
            task = self.get_stock_realtime_data(code)
            tasks.append((code, task))
        
        # 并发执行
        for code, task in tasks:
            try:
                data = await task
                if data:
                    results[code] = data
            except Exception as e:
                logger.error(f"获取股票数据失败 {code}: {e}")
        
        return results


# 全局API实例（单例模式）
_api_instance = None

async def get_eastmoney_api() -> EastMoneyAPIService:
    """获取东方财富API实例"""
    global _api_instance
    if _api_instance is None:
        _api_instance = EastMoneyAPIService()
    return _api_instance
