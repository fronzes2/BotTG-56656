"""
CS2 Trading Bot - Полный бот для торговли скинами
Версия: 1.0 (Исправленная)

Установка:
pip install python-telegram-bot==20.7 aiohttp beautifulsoup4 python-dotenv

Запуск:
python cs2_trading_bot.py
"""

import logging
import asyncio
from datetime import datetime, timedelta, time
from typing import Dict, List, Optional
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)
import os

# Попытка загрузить dotenv
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_TELEGRAM_BOT_TOKEN')
STEAM_API_KEY = os.getenv('STEAM_API_KEY', 'YOUR_STEAM_API_KEY')

POPULAR_ITEMS = [
    "AK-47 | Redline (Field-Tested)",
    "AWP | Asiimov (Field-Tested)",
    "M4A4 | Howl (Factory New)",
    "Desert Eagle | Blaze (Factory New)",
    "USP-S | Orion (Factory New)",
    "Glock-18 | Fade (Factory New)",
    "Karambit | Doppler (Factory New)",
    "Butterfly Knife | Fade (Factory New)"
]

PRICE_CHECK_INTERVAL = 1800
NEWS_CHECK_INTERVAL = 3600

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================================
# ХРАНИЛИЩЕ ДАННЫХ
# ============================================================================

user_data: Dict = {}
news_cache: List = []

# ============================================================================
# STEAM MARKET API
# ============================================================================

class SteamMarketAPI:
    """Класс для работы с Steam Market"""
    
    BASE_URL = "https://steamcommunity.com/market"
    CSGO_APP_ID = 730
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def init_session(self):
        if not self.session or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
    
    async def close_session(self):
        if self.session and not self.session.closed:
            await self.session.close()
            await asyncio.sleep(0.25)
    
    async def get_item_price(self, item_name: str) -> Optional[Dict]:
        """Получить текущую цену предмета"""
        await self.init_session()
        url = f"{self.BASE_URL}/priceoverview/"
        params = {
            'appid': self.CSGO_APP_ID,
            'currency': 1,
            'market_hash_name': item_name
        }
        
        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('success'):
                        return {
                            'lowest_price': data.get('lowest_price', 'N/A'),
                            'median_price': data.get('median_price', 'N/A'),
                            'volume': data.get('volume', 'N/A')
                        }
        except Exception as e:
            logger.error(f"Error fetching price for {item_name}: {e}")
        return None

# ============================================================================
# АНАЛИТИКА ЦЕН
# ============================================================================

class PriceAnalyzer:
    """Анализ цен и выявление трендов"""
    
    def __init__(self):
        self.price_history: Dict[str, List[Dict]] = {}
    
    def add_price_point(self, item_name: str, price: float):
        """Добавить точку цены в историю"""
        if item_name not in self.price_history:
            self.price_history[item_name] = []
        
        self.price_history[item_name].append({
            'price': price,
            'timestamp': datetime.now()
        })
        
        cutoff = datetime.now() - timedelta(days=30)
        self.price_history[item_name] = [
            p for p in self.price_history[item_name]
            if p['timestamp'] > cutoff
        ]
    
    def detect_trend(self, item_name: str) -> str:
        """Определить тренд цены"""
        if item_name not in self.price_history or len(self.price_history[item_name]) < 3:
            return "📊 Недостаточно данных"
        
        recent = self.price_history[item_name][-7:]
        prices = [p['price'] for p in recent]
        
        if len(prices) < 2:
            return "📊 Недостаточно данных"
        
        try:
            if all(prices[i] < prices[i+1] for i in range(len(prices)-1)):
                return "📈 Стабильный рост"
            elif all(prices[i] > prices[i+1] for i in range(len(prices)-1)):
                return "📉 Падение цены"
            elif prices[-1] > prices[0] * 1.1:
                return "💹 Сильный рост (+10%+)"
            elif prices[-1] < prices[0] * 0.9:
                return "⚠️ Сильное падение (-10%+)"
            else:
                return "➡️ Стабильная цена"
        except (IndexError, ZeroDivisionError):
            return "📊 Недостаточно данных"
    
    def calculate_profit_potential(self, item_name: str) -> int:
        """Рассчитать потенциал прибыли (0-100)"""
        if item_name not in self.price_history or len(self.price_history[item_name]) < 5:
            return 50
        
        recent = self.price_history[item_name][-14:]
        prices = [p['price'] for p in recent]
        
        try:
            min_price = min(prices)
            max_price = max(prices)
            
            if min_price == 0:
                return 50
            
            volatility = ((max_price - min_price) / min_price) * 100
            trend = ((prices[-1] - prices[0]) / prices[0]) * 100
            
            potential = 50 + (trend * 2) + (volatility * 0.5)
            return max(0, min(100, int(potential)))
        except (ZeroDivisionError, ValueError):
            return 50
    
    def predict_price(self, item_name: str, days: int = 7) -> Dict:
        """Предсказание движения цены"""
        if item_name not in self.price_history or len(self.price_history[item_name]) < 10:
            return {
                'prediction': 'neutral',
                'confidence': 0,
                'message': '❓ Недостаточно данных'
            }
        
        data = self.price_history[item_name][-30:]
        prices = [d['price'] for d in data]
        
        try:
            n = len(prices)
            x_mean = n / 2
            y_mean = sum(prices) / n
            
            numerator = sum((i - x_mean) * (prices[i] - y_mean) for i in range(n))
            denominator = sum((i - x_mean) ** 2 for i in range(n))
            
            if denominator == 0:
                slope = 0
            else:
                slope = numerator / denominator
            
            predicted_change = slope * days
            current_price = prices[-1]
            
            if current_price == 0:
                return {
                    'prediction': 'neutral',
                    'confidence': 0,
                    'message': '❓ Ошибка данных'
                }
            
            change_percent = (predicted_change / current_price) * 100
            
            if change_percent > 5:
                return {
                    'prediction': 'bullish',
                    'confidence': min(85, int(60 + abs(change_percent))),
                    'message': f'📈 Прогноз: рост ~{change_percent:.1f}% за {days}д'
                }
            elif change_percent < -5:
                return {
                    'prediction': 'bearish',
                    'confidence': min(85, int(60 + abs(change_percent))),
                    'message': f'📉 Прогноз: падение ~{abs(change_percent):.1f}% за {days}д'
                }
            else:
                return {
                    'prediction': 'neutral',
                    'confidence': 70,
                    'message': f'➡️ Прогноз: стабильность за {days}д'
                }
        except (ZeroDivisionError, ValueError, IndexError):
            return {
                'prediction': 'neutral',
                'confidence': 0,
                'message': '❓ Ошибка расчета'
            }

# ============================================================================
# ПАРСЕР НОВОСТЕЙ
# ============================================================================

class NewsParser:
    """Парсер новостей CS2"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def init_session(self):
        if not self.session or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
    
    async def close_session(self):
        if self.session and not self.session.closed:
            await self.session.close()
            await asyncio.sleep(0.25)
    
    async def get_steam_news(self) -> List[Dict]:
        """Получить новости Steam"""
        await self.init_session()
        
        url = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
        params = {
            'appid': 730,
            'count': 5,
            'maxlength': 300
        }
        
        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    news_items = []
                    
                    for item in data.get('appnews', {}).get('newsitems', [])[:5]:
                        news_items.append({
                            'source': '🎮 Steam',
                            'title': item.get('title', 'Без названия'),
                            'date': datetime.fromtimestamp(item.get('date', 0)).strftime('%d.%m.%Y'),
                            'impact': self.analyze_impact(item.get('title', '')),
                            'url': item.get('url', '')
                        })
                    
                    return news_items
        except Exception as e:
            logger.error(f"Error fetching Steam news: {e}")
        
        return []
    
    def analyze_impact(self, title: str) -> str:
        """Анализ влияния новости"""
        title_lower = title.lower()
        
        high_keywords = ['case', 'кейс', 'operation', 'операция', 'update', 'обновление']
        medium_keywords = ['patch', 'патч', 'balance', 'баланс', 'fix', 'исправление']
        
        if any(k in title_lower for k in high_keywords):
            return '🔥 Высокое'
        elif any(k in title_lower for k in medium_keywords):
            return '⚠️ Среднее'
        else:
            return 'ℹ️ Низкое'

# ============================================================================
# СОВЕТЧИК ПО ИНВЕСТИЦИЯМ
# ============================================================================

class InvestmentAdvisor:
    """Умный советчик"""
    
    @staticmethod
    def analyze_item(price_data: Dict, trend: str, potential: int, mode: str) -> Dict:
        """Анализ предмета для инвестиций"""
        analysis = {
            'rating': 0,
            'recommendation': '',
            'strategy': '',
            'pros': [],
            'cons': []
        }
        
        rating = 50
        
        if 'рост' in trend.lower():
            rating += 15
            analysis['pros'].append('📈 Положительный тренд')
        
        try:
            volume_str = str(price_data.get('volume', '0')).replace(',', '')
            volume = int(volume_str)
            if volume > 100:
                rating += 10
                analysis['pros'].append('💰 Высокая ликвидность')
        except (ValueError, AttributeError):
            pass
        
        if potential > 70:
            rating += 10
            analysis['pros'].append('⚡ Высокий потенциал')
        
        if 'падение' in trend.lower():
            rating -= 15
            analysis['cons'].append('📉 Отрицательный тренд')
        
        analysis['rating'] = max(0, min(100, rating))
        
        if mode == 'investor':
            if analysis['rating'] > 70:
                analysis['recommendation'] = '🟢 ПОКУПАТЬ'
                analysis['strategy'] = 'Держать 3-6 месяцев, продать при +20-30%'
            elif analysis['rating'] > 50:
                analysis['recommendation'] = '🟡 НАБЛЮДАТЬ'
                analysis['strategy'] = 'Дождаться подтверждения тренда'
            else:
                analysis['recommendation'] = '🔴 НЕ ПОКУПАТЬ'
                analysis['strategy'] = 'Высокий риск, искать альтернативы'
        else:
            if analysis['rating'] > 60:
                analysis['recommendation'] = '🟢 ПОКУПАТЬ'
                analysis['strategy'] = 'Держать 1-2 недели, фиксировать при +10-15%'
            elif analysis['rating'] > 45:
                analysis['recommendation'] = '🟡 ВОЗМОЖНА ПОКУПКА'
                analysis['strategy'] = 'Стоп-лосс на -5%'
            else:
                analysis['recommendation'] = '🔴 ПРОПУСТИТЬ'
                analysis['strategy'] = 'Недостаточно волатильности'
        
        return analysis

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================================

steam_api = SteamMarketAPI(STEAM_API_KEY)
analyzer = PriceAnalyzer()
news_parser = NewsParser()

# ============================================================================
# ОБРАБОТЧИКИ КОМАНД
# ============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user_id = update.effective_user.id
    
    if user_id not in user_data:
        user_data[user_id] = {
            'mode': 'investor',
            'portfolio': [],
            'notifications': True,
            'alerts': []
        }
    
    keyboard = [
        [InlineKeyboardButton("💎 Режим Инвестора", callback_data='mode_investor')],
        [InlineKeyboardButton("⚡ Режим Трейдера", callback_data='mode_trader')],
        [InlineKeyboardButton("📰 Только новости", callback_data='mode_news')],
        [InlineKeyboardButton("💼 Мой портфель", callback_data='portfolio')],
        [InlineKeyboardButton("📊 Топ предметов", callback_data='top_items')],
        [InlineKeyboardButton("📰 Последние новости", callback_data='news')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = """
🎮 <b>CS2 Trading Bot</b> - Ваш помощник в торговле скинами!

<b>🚀 Возможности:</b>
💹 Анализ цен и трендов
📈 Прогнозы движения рынка
🔔 Умные уведомления
💼 Управление портфелем
📰 Новости CS2

<b>Выберите режим:</b>
"""
    
    await update.message.reply_text(
        welcome_text,
        parse_mode='HTML',
        reply_markup=reply_markup
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопок"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    try:
        if data.startswith('mode_'):
            await handle_mode_change(query, user_id, data)
        elif data == 'portfolio':
            await show_portfolio(query, user_id)
        elif data == 'top_items':
            await show_top_items(query, user_id)
        elif data == 'news':
            await show_news(query)
        elif data.startswith('item_'):
            item_idx = int(data.split('_')[1])
            await show_item_details(query, user_id, item_idx)
        elif data.startswith('add_'):
            item_idx = int(data.split('_')[1])
            await add_to_portfolio(query, user_id, item_idx)
        elif data.startswith('analyze_'):
            item_idx = int(data.split('_')[1])
            await show_analysis(query, user_id, item_idx)
        elif data == 'back':
            keyboard = [
                [InlineKeyboardButton("📊 Топ предметов", callback_data='top_items')],
                [InlineKeyboardButton("💼 Мой портфель", callback_data='portfolio')],
                [InlineKeyboardButton("📰 Новости", callback_data='news')],
            ]
            await query.edit_message_text(
                "📋 <b>Главное меню</b>\n\nВыберите действие:",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except Exception as e:
        logger.error(f"Error in callback: {e}")
        await query.answer("Произошла ошибка, попробуйте снова")

async def handle_mode_change(query, user_id: int, data: str):
    """Смена режима"""
    mode = data.replace('mode_', '')
    user_data[user_id]['mode'] = mode
    
    modes = {
        'investor': ('💎 Инвестор', 'Фокус на долгосрочных инвестициях\nРиск: низкий-средний\nСрок: 3-6 месяцев'),
        'trader': ('⚡ Трейдер', 'Быстрые сделки и прибыль\nРиск: средний-высокий\nСрок: 1-4 недели'),
        'news': ('📰 Новости', 'Только важные обновления\nМинимум уведомлений')
    }
    
    name, desc = modes.get(mode, ('💎 Инвестор', 'Режим по умолчанию'))
    keyboard = [[InlineKeyboardButton("🔙 В меню", callback_data='back')]]
    
    await query.edit_message_text(
        f"✅ <b>Режим изменен: {name}</b>\n\n{desc}\n\n"
        f"Используйте /menu для доступа к функциям.",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_portfolio(query, user_id: int):
    """Показать портфель"""
    portfolio = user_data[user_id].get('portfolio', [])
    
    if not portfolio:
        text = "💼 <b>Ваш портфель пуст</b>\n\nДобавьте скины через 'Топ предметов' 👇"
        keyboard = [
            [InlineKeyboardButton("📊 Топ предметов", callback_data='top_items')],
            [InlineKeyboardButton("🔙 Назад", callback_data='back')]
        ]
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    text = "💼 <b>Ваш портфель:</b>\n\n"
    total = 0.0
    
    for idx in portfolio:
        if idx >= len(POPULAR_ITEMS):
            continue
            
        item = POPULAR_ITEMS[idx]
        price_data = await steam_api.get_item_price(item)
        
        if price_data:
            price_str = price_data.get('median_price', '$0')
            trend = analyzer.detect_trend(item)
            
            text += f"<b>{item}</b>\n💰 {price_str} | {trend}\n\n"
            
            try:
                price_val = float(price_str.replace(',', ''))
                total += price_val
            except (ValueError, AttributeError):
                pass
    
    text += f"\n<b>💵 Общая стоимость: ${total:.2f}</b>"
    
    keyboard = [
        [InlineKeyboardButton("📊 Топ предметов", callback_data='top_items')],
        [InlineKeyboardButton("🔙 Назад", callback_data='back')]
    ]
    
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def show_top_items(query, user_id: int):
    """Показать топ предметов"""
    text = "📊 <b>Популярные предметы CS2:</b>\n\n"
    
    keyboard = []
    for i, item in enumerate(POPULAR_ITEMS[:8]):
        price_data = await steam_api.get_item_price(item)
        
        if price_data:
            price = price_data.get('median_price', 'N/A')
            potential = analyzer.calculate_profit_potential(item)
            
            try:
                price_val = float(price.replace('$', '').replace(',', ''))
                analyzer.add_price_point(item, price_val)
            except (ValueError, AttributeError):
                pass
            
            emoji = '🟢' if potential > 70 else '🟡' if potential > 50 else '🟠'
            text += f"{i+1}. <b>{item}</b>\n   💰 {price} | {emoji} Потенциал: {potential}/100\n\n"
            
            short_name = item.split('|')[0].strip()[:20]
            keyboard.append([InlineKeyboardButton(f"{i+1}. {short_name}", callback_data=f"item_{i}")])
        
        await asyncio.sleep(0.5)
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='back')])
    
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def show_item_details(query, user_id: int, item_idx: int):
    """Детали предмета"""
    if item_idx >= len(POPULAR_ITEMS):
        await query.answer("Предмет не найден")
        return
    
    item = POPULAR_ITEMS[item_idx]
    price_data = await steam_api.get_item_price(item)
    
    if not price_data:
        await query.edit_message_text("❌ Не удалось получить данные")
        return
    
    trend = analyzer.detect_trend(item)
    potential = analyzer.calculate_profit_potential(item)
    prediction = analyzer.predict_price(item, 7)
    
    text = f"📦 <b>{item}</b>\n\n"
    text += f"💰 <b>Цены:</b>\n"
    text += f"• Минимальная: {price_data.get('lowest_price', 'N/A')}\n"
    text += f"• Средняя: {price_data.get('median_price', 'N/A')}\n\n"
    text += f"📊 <b>Статистика:</b>\n"
    text += f"• Объем: {price_data.get('volume', 'N/A')}\n"
    text += f"• Тренд: {trend}\n"
    text += f"• Потенциал: {potential}/100\n\n"
    text += f"🔮 <b>Прогноз (7 дней):</b>\n{prediction['message']}\n"
    text += f"Уверенность: {prediction['confidence']}%\n\n"
    
    if potential > 70:
        text += "💡 <b>Рекомендация:</b> 🟢 Отличная инвестиция!"
    elif potential > 50:
        text += "💡 <b>Рекомендация:</b> 🟡 Средний потенциал"
    else:
        text += "💡 <b>Рекомендация:</b> 🔴 Рискованно"
    
    keyboard = [
        [InlineKeyboardButton("➕ В портфель", callback_data=f"add_{item_idx}"),
         InlineKeyboardButton("📈 Анализ", callback_data=f"analyze_{item_idx}")],
        [InlineKeyboardButton("🔙 К списку", callback_data='top_items')]
    ]
    
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def add_to_portfolio(query, user_id: int, item_idx: int):
    """Добавить в портфель"""
    if item_idx not in user_data[user_id]['portfolio']:
        user_data[user_id]['portfolio'].append(item_idx)
        await query.answer("✅ Добавлено в портфель!")
    else:
        await query.answer("ℹ️ Уже в портфеле")

async def show_analysis(query, user_id: int, item_idx: int):
    """Детальный анализ"""
    if item_idx >= len(POPULAR_ITEMS):
        return
    
    item = POPULAR_ITEMS[item_idx]
    price_data = await steam_api.get_item_price(item)
    
    if not price_data:
        await query.answer("❌ Ошибка получения данных")
        return
    
    trend = analyzer.detect_trend(item)
    potential = analyzer.calculate_profit_potential(item)
    mode = user_data[user_id]['mode']
    
    analysis = InvestmentAdvisor.analyze_item(price_data, trend, potential, mode)
    
    text = f"🔍 <b>Детальный анализ:</b>\n<b>{item}</b>\n\n"
    text += f"⭐ <b>Рейтинг:</b> {analysis['rating']}/100\n\n"
    text += f"📌 <b>Рекомендация:</b> {analysis['recommendation']}\n"
    text += f"💡 <b>Стратегия:</b> {analysis['strategy']}\n\n"
    
    if analysis['pros']:
        text += "<b>✅ Плюсы:</b>\n"
        for pro in analysis['pros']:
            text += f"  • {pro}\n"
        text += "\n"
    
    if analysis['cons']:
        text += "<b>❌ Минусы:</b>\n"
        for con in analysis['cons']:
            text += f"  • {con}\n"
    
    keyboard = [
        [InlineKeyboardButton("➕ В портфель", callback_data=f"add_{item_idx}")],
        [InlineKeyboardButton("🔙 Назад", callback_data=f"item_{item_idx}")]
    ]
    
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def show_news(query):
    """Показать новости"""
    global news_cache
    
    news_needs_update = not news_cache
    if news_cache:
        first_item = news_cache[0]
        if 'fetched' in first_item:
            age = (datetime.now() - first_item['fetched']).total_seconds()
            if age > 3600:
                news_needs_update = True
    
    if news_needs_update:
        news_items = await news_parser.get_steam_news()
        for item in news_items:
            item['fetched'] = datetime.now()
        news_cache = news_items
    else:
        news_items = news_cache
    
    if not news_items:
        text = "📰 <b>Новостей пока нет</b>"
    else:
        text = "📰 <b>Последние новости CS2:</b>\n\n"
        for i, item in enumerate(news_items[:5], 1):
            text += f"{i}. <b>{item['title']}</b>\n"
            text += f"   📅 {item['date']} | {item['source']}\n"
            text += f"   Влияние: {item['impact']}\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='back')]]
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /menu"""
    keyboard = [
        [InlineKeyboardButton("📊 Топ предметов", callback_data='top_items')],
        [InlineKeyboardButton("💼 Мой портфель", callback_data='portfolio')],
        [InlineKeyboardButton("📰 Новости", callback_data='news')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📋 <b>Главное меню</b>\n\nВыберите действие:",
        parse_mode='HTML',
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    help_text = """
<b>📖 Справка по командам:</b>

<b>Основные команды:</b>
/start - Начать работу
/menu - Главное меню
/portfolio - Мой портфель
/top - Топ предметов
/news - Новости
/help - Справка

<b>🎯 Режимы работы:</b>

<b>💎 Инвестор</b>
• Долгосрочные вложения (3-6 мес)
• Низкий/средний риск

<b>⚡ Трейдер</b>
• Краткосрочная торговля (1-4 недели)
• Средний/высокий риск

<b>📰 Новости</b>
• Только важные обновления

<b>⚠️ Дисклеймер:</b>
Бот предоставляет аналитику, но не является финансовым советником. Все решения на ваш риск.
"""
    
    await update.message.reply_text(help_text, parse_mode='HTML')

async def portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /portfolio"""
    user_id = update.effective_user.id
    
    if user_id not in user_data:
        user_data[user_id] = {
            'mode': 'investor',
            'portfolio': [],
            'notifications': True,
            'alerts': []
        }
    
    portfolio = user_data[user_id].get('portfolio', [])
    
    if not portfolio:
        text = "💼 <b>Ваш портфель пуст</b>\n\nИспользуйте /top для просмотра предметов"
        await update.message.reply_text(text, parse_mode='HTML')
        return
    
    text = "💼 <b>Ваш портфель:</b>\n\n"
    total = 0.0
    
    for idx in portfolio:
        if idx >= len(POPULAR_ITEMS):
            continue
            
        item = POPULAR_ITEMS[idx]
        price_data = await steam_api.get_item_price(item)
        
        if price_data:
            price_str = price_data.get('median_price', '$0')
            trend = analyzer.detect_trend(item)
            
            text += f"<b>{item}</b>\n💰 {price_str} | {trend}\n\n"
            
            try:
                price_val = float(price_str.replace('$', '').replace(',', ''))
                total += price_val
            except (ValueError, AttributeError):
                pass
    
    text += f"\n<b>💵 Общая стоимость: ${total:.2f}</b>"
    await update.message.reply_text(text, parse_mode='HTML')

async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /top"""
    text = "📊 <b>Топ-5 предметов:</b>\n\n"
    
    for i, item in enumerate(POPULAR_ITEMS[:5], 1):
        price_data = await steam_api.get_item_price(item)
        
        if price_data:
            price = price_data.get('median_price', 'N/A')
            potential = analyzer.calculate_profit_potential(item)
            
            emoji = '🟢' if potential > 70 else '🟡' if potential > 50 else '🟠'
            text += f"{i}. <b>{item}</b>\n   💰 {price} | {emoji} {potential}/100\n\n"
        
        await asyncio.sleep(0.5)
    
    text += "\nИспользуйте /menu для детального просмотра"
    await update.message.reply_text(text, parse_mode='HTML')

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /news"""
    global news_cache
    
    news_needs_update = not news_cache
    if news_cache:
        first_item = news_cache[0]
        if 'fetched' in first_item:
            age = (datetime.now() - first_item['fetched']).total_seconds()
            if age > 3600:
                news_needs_update = True
    
    if news_needs_update:
        news_items = await news_parser.get_steam_news()
        for item in news_items:
            item['fetched'] = datetime.now()
        news_cache = news_items
    else:
        news_items = news_cache
    
    if not news_items:
        text = "📰 <b>Новостей пока нет</b>"
    else:
        text = "📰 <b>Последние новости CS2:</b>\n\n"
        for i, item in enumerate(news_items[:5], 1):
            text += f"{i}. <b>{item['title']}</b>\n"
            text += f"   📅 {item['date']} | {item['source']}\n"
            text += f"   Влияние: {item['impact']}\n\n"
    
    await update.message.reply_text(text, parse_mode='HTML')

# ============================================================================
# ФОНОВЫЕ ЗАДАЧИ
# ============================================================================

async def monitor_prices(context: ContextTypes.DEFAULT_TYPE):
    """Периодический мониторинг цен"""
    logger.info("Starting price monitoring...")
    
    for item in POPULAR_ITEMS[:5]:  # Ограничим количество для избежания перегрузки
        try:
            price_data = await steam_api.get_item_price(item)
            
            if price_data and price_data.get('median_price'):
                try:
                    price_str = str(price_data['median_price']).replace('$', '').replace(',', '')
                    price = float(price_str)
                    analyzer.add_price_point(item, price)
                    
                    trend = analyzer.detect_trend(item)
                    potential = analyzer.calculate_profit_potential(item)
                    
                    if "Сильный рост" in trend or potential > 75:
                        for user_id, data in list(user_data.items()):
                            if data.get('notifications') and data.get('mode') != 'news':
                                try:
                                    message = f"🔔 <b>Торговый сигнал!</b>\n\n"
                                    message += f"📦 <b>{item}</b>\n"
                                    message += f"💰 Цена: {price_data['median_price']}\n"
                                    message += f"📊 {trend}\n"
                                    message += f"⭐ Потенциал: {potential}/100\n\n"
                                    message += f"💡 Рассмотрите покупку!"
                                    
                                    await context.bot.send_message(
                                        chat_id=user_id,
                                        text=message,
                                        parse_mode='HTML'
                                    )
                                except Exception as e:
                                    logger.error(f"Error sending signal to {user_id}: {e}")
                
                except (ValueError, AttributeError) as e:
                    logger.error(f"Error parsing price for {item}: {e}")
            
            await asyncio.sleep(2)
            
        except Exception as e:
            logger.error(f"Error monitoring {item}: {e}")
    
    logger.info("Price monitoring completed")

async def check_news(context: ContextTypes.DEFAULT_TYPE):
    """Проверка новостей"""
    global news_cache
    
    logger.info("Checking for news...")
    
    try:
        news_items = await news_parser.get_steam_news()
        
        if not news_items:
            return
        
        new_news = []
        if news_cache:
            cached_titles = {item.get('title') for item in news_cache if 'title' in item}
            new_news = [item for item in news_items if item.get('title') not in cached_titles]
        else:
            new_news = news_items[:1]
        
        for item in news_items:
            item['fetched'] = datetime.now()
        news_cache = news_items
        
        for news_item in new_news:
            if news_item.get('impact') in ['🔥 Высокое', '⚠️ Среднее']:
                for user_id, data in list(user_data.items()):
                    if data.get('notifications'):
                        try:
                            message = f"📰 <b>Важная новость CS2!</b>\n\n"
                            message += f"<b>{news_item.get('title', 'Без названия')}</b>\n\n"
                            message += f"📅 {news_item.get('date', 'N/A')}\n"
                            message += f"Влияние: {news_item.get('impact', 'N/A')}"
                            
                            await context.bot.send_message(
                                chat_id=user_id,
                                text=message,
                                parse_mode='HTML'
                            )
                        except Exception as e:
                            logger.error(f"Error sending news to {user_id}: {e}")
        
        logger.info(f"Found {len(new_news)} new news items")
        
    except Exception as e:
        logger.error(f"Error checking news: {e}")

async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):
    """Ежедневный отчет"""
    logger.info("Sending daily reports...")
    
    for user_id, data in list(user_data.items()):
        if not data.get('notifications') or data.get('mode') == 'news':
            continue
        
        try:
            portfolio = data.get('portfolio', [])
            
            if not portfolio:
                continue
            
            text = "📊 <b>Ежедневный отчет</b>\n\n"
            total_value = 0.0
            growing = 0
            falling = 0
            
            for idx in portfolio:
                if idx >= len(POPULAR_ITEMS):
                    continue
                
                item = POPULAR_ITEMS[idx]
                price_data = await steam_api.get_item_price(item)
                
                if price_data:
                    trend = analyzer.detect_trend(item)
                    
                    if 'рост' in trend.lower():
                        growing += 1
                    elif 'падение' in trend.lower():
                        falling += 1
                    
                    try:
                        price_str = str(price_data.get('median_price', '$0')).replace(', '').replace(',', '')
                        total_value += float(price_str)
                    except (ValueError, AttributeError):
                        pass
                
                await asyncio.sleep(0.5)
            
            text += f"💼 <b>Портфель:</b> {len(portfolio)} предметов\n"
            text += f"💰 <b>Стоимость:</b> ${total_value:.2f}\n\n"
            text += f"📈 Растут: {growing}\n"
            text += f"📉 Падают: {falling}\n"
            text += f"➡️ Стабильны: {len(portfolio) - growing - falling}\n\n"
            
            if growing > falling:
                text += "✅ Хороший день! Портфель растет."
            elif falling > growing:
                text += "⚠️ Портфель снижается. Проверьте позиции."
            else:
                text += "➡️ Стабильный день на рынке."
            
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode='HTML'
            )
            
        except Exception as e:
            logger.error(f"Error sending report to {user_id}: {e}")
    
    logger.info("Daily reports sent")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ошибок"""
    logger.error(f"Update {update} caused error {context.error}")
    
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "❌ Произошла ошибка. Попробуйте позже или используйте /start"
            )
    except Exception as e:
        logger.error(f"Error in error_handler: {e}")

# ============================================================================
# ЗАПУСК БОТА
# ============================================================================

async def post_init(application: Application):
    """Действия после инициализации"""
    logger.info("Bot initialized successfully!")
    await steam_api.init_session()
    await news_parser.init_session()

async def post_shutdown(application: Application):
    """Действия при остановке"""
    logger.info("Shutting down...")
    await steam_api.close_session()
    await news_parser.close_session()

def main():
    """Главная функция"""
    
    if TELEGRAM_TOKEN == 'YOUR_TELEGRAM_BOT_TOKEN':
        print("=" * 60)
        print("❌ ОШИБКА: Не установлены токены!")
        print("=" * 60)
        print("\n📝 Создайте файл .env с содержимым:\n")
        print("TELEGRAM_BOT_TOKEN=ваш_токен_от_BotFather")
        print("STEAM_API_KEY=ваш_steam_api_ключ")
        print("\n📖 Инструкция:")
        print("1. Telegram Token: https://t.me/BotFather -> /newbot")
        print("2. Steam API Key: https://steamcommunity.com/dev/apikey")
        print("=" * 60)
        return
    
    try:
        application = Application.builder().token(TELEGRAM_TOKEN).build()
        
        # Обработчики команд
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("menu", menu))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("portfolio", portfolio_command))
        application.add_handler(CommandHandler("top", top_command))
        application.add_handler(CommandHandler("news", news_command))
        
        # Обработчик кнопок
        application.add_handler(CallbackQueryHandler(button_callback))
        
        # Обработчик ошибок
        application.add_error_handler(error_handler)
        
        # Фоновые задачи
        job_queue = application.job_queue
        
        # Мониторинг цен каждые 30 минут
        job_queue.run_repeating(monitor_prices, interval=PRICE_CHECK_INTERVAL, first=60)
        
        # Проверка новостей каждый час
        job_queue.run_repeating(check_news, interval=NEWS_CHECK_INTERVAL, first=120)
        
        # Ежедневный отчет в 9:00
        job_queue.run_daily(send_daily_report, time=time(hour=9, minute=0))
        
        # Хуки инициализации
        application.post_init = post_init
        application.post_shutdown = post_shutdown
        
        # Запуск
        print("=" * 60)
        print("🎮 CS2 Trading Bot успешно запущен!")
        print("=" * 60)
        print("✅ Мониторинг цен: каждые 30 минут")
        print("✅ Проверка новостей: каждый час")
        print("✅ Ежедневный отчет: 09:00")
        print("=" * 60)
        print("🤖 Бот работает... Нажмите Ctrl+C для остановки")
        print("=" * 60)
        
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"\n❌ Критическая ошибка: {e}")
        print("Проверьте токены и интернет-соединение")

if __name__ == '__main__':
    main(), '').replace(',', ''))
                total += price_val
            except (ValueError, AttributeError):
                pass
    
    text += f"\n<b>💵 Общая стоимость: ${total:.2f}</b>"
    
    keyboard = [
        [InlineKeyboardButton("📊 Топ предметов", callback_data='top_items')],
        [InlineKeyboardButton("🔙 Назад", callback_data='back')]
    ]
    
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def show_top_items(query, user_id: int):
    """Показать топ предметов"""
    text = "📊 <b>Популярные предметы CS2:</b>\n\n"
    
    keyboard = []
    for i, item in enumerate(POPULAR_ITEMS[:8]):
        price_data = await steam_api.get_item_price(item)
        
        if price_data:
            price = price_data.get('median_price', 'N/A')
            potential = analyzer.calculate_profit_potential(item)
            
            try:
                price_val = float(price.replace('$', '').replace(',', ''))
                analyzer.add_price_point(item, price_val)
            except (ValueError, AttributeError):
                pass
            
            emoji = '🟢' if potential > 70 else '🟡' if potential > 50 else '🟠'
            text += f"{i+1}. <b>{item}</b>\n   💰 {price} | {emoji} Потенциал: {potential}/100\n\n"
            
            short_name = item.split('|')[0].strip()[:20]
            keyboard.append([InlineKeyboardButton(f"{i+1}. {short_name}", callback_data=f"item_{i}")])
        
        await asyncio.sleep(0.5)
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='back')])
    
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def show_item_details(query, user_id: int, item_idx: int):
    """Детали предмета"""
    if item_idx >= len(POPULAR_ITEMS):
        await query.answer("Предмет не найден")
        return
    
    item = POPULAR_ITEMS[item_idx]
    price_data = await steam_api.get_item_price(item)
    
    if not price_data:
        await query.edit_message_text("❌ Не удалось получить данные")
        return
    
    trend = analyzer.detect_trend(item)
    potential = analyzer.calculate_profit_potential(item)
    prediction = analyzer.predict_price(item, 7)
    
    text = f"📦 <b>{item}</b>\n\n"
    text += f"💰 <b>Цены:</b>\n"
    text += f"• Минимальная: {price_data.get('lowest_price', 'N/A')}\n"
    text += f"• Средняя: {price_data.get('median_price', 'N/A')}\n\n"
    text += f"📊 <b>Статистика:</b>\n"
    text += f"• Объем: {price_data.get('volume', 'N/A')}\n"
    text += f"• Тренд: {trend}\n"
    text += f"• Потенциал: {potential}/100\n\n"
    text += f"🔮 <b>Прогноз (7 дней):</b>\n{prediction['message']}\n"
    text += f"Уверенность: {prediction['confidence']}%\n\n"
    
    if potential > 70:
        text += "💡 <b>Рекомендация:</b> 🟢 Отличная инвестиция!"
    elif potential > 50:
        text += "💡 <b>Рекомендация:</b> 🟡 Средний потенциал"
    else:
        text += "💡 <b>Рекомендация:</b> 🔴 Рискованно"
    
    keyboard = [
        [InlineKeyboardButton("➕ В портфель", callback_data=f"add_{item_idx}"),
         InlineKeyboardButton("📈 Анализ", callback_data=f"analyze_{item_idx}")],
        [InlineKeyboardButton("🔙 К списку", callback_data='top_items')]
    ]
    
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def add_to_portfolio(query, user_id: int, item_idx: int):
    """Добавить в портфель"""
    if item_idx not in user_data[user_id]['portfolio']:
        user_data[user_id]['portfolio'].append(item_idx)
        await query.answer("✅ Добавлено в портфель!")
    else:
        await query.answer("ℹ️ Уже в портфеле")

async def show_analysis(query, user_id: int, item_idx: int):
    """Детальный анализ"""
    if item_idx >= len(POPULAR_ITEMS):
        return
    
    item = POPULAR_ITEMS[item_idx]
    price_data = await steam_api.get_item_price(item)
    
    if not price_data:
        await query.answer("❌ Ошибка получения данных")
        return
    
    trend = analyzer.detect_trend(item)
    potential = analyzer.calculate_profit_potential(item)
    mode = user_data[user_id]['mode']
    
    analysis = InvestmentAdvisor.analyze_item(price_data, trend, potential, mode)
    
    text = f"🔍 <b>Детальный анализ:</b>\n<b>{item}</b>\n\n"
    text += f"⭐ <b>Рейтинг:</b> {analysis['rating']}/100\n\n"
    text += f"📌 <b>Рекомендация:</b> {analysis['recommendation']}\n"
    text += f"💡 <b>Стратегия:</b> {analysis['strategy']}\n\n"
    
    if analysis['pros']:
        text += "<b>✅ Плюсы:</b>\n"
        for pro in analysis['pros']:
            text += f"  • {pro}\n"
        text += "\n"
    
    if analysis['cons']:
        text += "<b>❌ Минусы:</b>\n"
        for con in analysis['cons']:
            text += f"  • {con}\n"
    
    keyboard = [
        [InlineKeyboardButton("➕ В портфель", callback_data=f"add_{item_idx}")],
        [InlineKeyboardButton("🔙 Назад", callback_data=f"item_{item_idx}")]
    ]
    
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def show_news(query):
    """Показать новости"""
    global news_cache
    
    news_needs_update = not news_cache
    if news_cache:
        first_item = news_cache[0]
        if 'fetched' in first_item:
            age = (datetime.now() - first_item['fetched']).total_seconds()
            if age > 3600:
                news_needs_update = True
    
    if news_needs_update:
        news_items = await news_parser.get_steam_news()
        for item in news_items:
            item['fetched'] = datetime.now()
        news_cache = news_items
    else:
        news_items = news_cache
    
    if not news_items:
        text = "📰 <b>Новостей пока нет</b>"
    else:
        text = "📰 <b>Последние новости CS2:</b>\n\n"
        for i, item in enumerate(news_items[:5], 1):
            text += f"{i}. <b>{item['title']}</b>\n"
            text += f"   📅 {item['date']} | {item['source']}\n"
            text += f"   Влияние: {item['impact']}\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='back')]]
    await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /menu"""
    keyboard = [
        [InlineKeyboardButton("📊 Топ предметов", callback_data='top_items')],
        [InlineKeyboardButton("💼 Мой портфель", callback_data='portfolio')],
        [InlineKeyboardButton("📰 Новости", callback_data='news')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📋 <b>Главное меню</b>\n\nВыберите действие:",
        parse_mode='HTML',
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    help_text = """
<b>📖 Справка по командам:</b>

<b>Основные команды:</b>
/start - Начать работу
/menu - Главное меню
/portfolio - Мой портфель
/top - Топ предметов
/news - Новости
/help - Справка

<b>🎯 Режимы работы:</b>

<b>💎 Инвестор</b>
• Долгосрочные вложения (3-6 мес)
• Низкий/средний риск

<b>⚡ Трейдер</b>
• Краткосрочная торговля (1-4 недели)
• Средний/высокий риск

<b>📰 Новости</b>
• Только важные обновления

<b>⚠️ Дисклеймер:</b>
Бот предоставляет аналитику, но не является финансовым советником. Все решения на ваш риск.
"""
    
    await update.message.reply_text(help_text, parse_mode='HTML')

async def portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /portfolio"""
    user_id = update.effective_user.id
    
    if user_id not in user_data:
        user_data[user_id] = {
            'mode': 'investor',
            'portfolio': [],
            'notifications': True,
            'alerts': []
        }
    
    portfolio = user_data[user_id].get('portfolio', [])
    
    if not portfolio:
        text = "💼 <b>Ваш портфель пуст</b>\n\nИспользуйте /top для просмотра предметов"
        await update.message.reply_text(text, parse_mode='HTML')
        return
    
    text = "💼 <b>Ваш портфель:</b>\n\n"
    total = 0.0
    
    for idx in portfolio:
        if idx >= len(POPULAR_ITEMS):
            continue
            
        item = POPULAR_ITEMS[idx]
        price_data = await steam_api.get_item_price(item)
        
        if price_data:
            price_str = price_data.get('median_price', '$0')
            trend = analyzer.detect_trend(item)
            
            text += f"<b>{item}</b>\n💰 {price_str} | {trend}\n\n"
            
            try:
                price_val = float(price_str.replace(', '').replace(',', ''))
                total += price_val
            except (ValueError, AttributeError):
                pass
    
    text += f"\n<b>💵 Общая стоимость: ${total:.2f}</b>"
    await update.message.reply_text(text, parse_mode='HTML')

async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /top"""
    text = "📊 <b>Топ-5 предметов:</b>\n\n"
    
    for i, item in enumerate(POPULAR_ITEMS[:5], 1):
        price_data = await steam_api.get_item_price(item)
        
        if price_data:
            price = price_data.get('median_price', 'N/A')
            potential = analyzer.calculate_profit_potential(item)
            
            emoji = '🟢' if potential > 70 else '🟡' if potential > 50 else '🟠'
            text += f"{i}. <b>{item}</b>\n   💰 {price} | {emoji} {potential}/100\n\n"
        
        await asyncio.sleep(0.5)
    
    text += "\nИспользуйте /menu для детального просмотра"
    await update.message.reply_text(text, parse_mode='HTML')

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /news"""
    global news_cache
    
    news_needs_update = not news_cache
    if news_cache:
        first_item = news_cache[0]
        if 'fetched' in first_item:
            age = (datetime.now() - first_item['fetched']).total_seconds()
            if age > 3600:
                news_needs_update = True
    
    if news_needs_update:
        news_items = await news_parser.get_steam_news()
        for item in news_items:
            item['fetched'] = datetime.now()
        news_cache = news_items
    else:
        news_items = news_cache
    
    if not news_items:
        text = "📰 <b>Новостей пока нет</b>"
    else:
        text = "📰 <b>Последние новости CS2:</b>\n\n"
        for i, item in enumerate(news_items[:5], 1):
            text += f"{i}. <b>{item['title']}</b>\n"
            text += f"   📅 {item['date']} | {item['source']}\n"
            text += f"   Влияние: {item['impact']}\n\n"
    
    await update.message.reply_text(text, parse_mode='HTML')

# ============================================================================
# ФОНОВЫЕ ЗАДАЧИ
# ============================================================================

async def monitor_prices(context: ContextTypes.DEFAULT_TYPE):
    """Периодический мониторинг цен"""
    logger.info("Starting price monitoring...")
    
    for item in POPULAR_ITEMS[:5]:  # Ограничим количество для избежания перегрузки
        try:
            price_data = await steam_api.get_item_price(item)
            
            if price_data and price_data.get('median_price'):
                try:
                    price_str = str(price_data['median_price']).replace(', '').replace(',', '')
                    price = float(price_str)
                    analyzer.add_price_point(item, price)
                    
                    trend = analyzer.detect_trend(item)
                    potential = analyzer.calculate_profit_potential(item)
                    
                    if "Сильный рост" in trend or potential > 75:
                        for user_id, data in list(user_data.items()):
                            if data.get('notifications') and data.get('mode') != 'news':
                                try:
                                    message = f"🔔 <b>Торговый сигнал!</b>\n\n"
                                    message += f"📦 <b>{item}</b>\n"
                                    message += f"💰 Цена: {price_data['median_price']}\n"
                                    message += f"📊 {trend}\n"
                                    message += f"⭐ Потенциал: {potential}/100\n\n"
                                    message += f"💡 Рассмотрите покупку!"
                                    
                                    await context.bot.send_message(
                                        chat_id=user_id,
                                        text=message,
                                        parse_mode='HTML'
                                    )
                                except Exception as e:
                                    logger.error(f"Error sending signal to {user_id}: {e}")
                
                except (ValueError, AttributeError) as e:
                    logger.error(f"Error parsing price for {item}: {e}")
            
            await asyncio.sleep(2)
            
        except Exception as e:
            logger.error(f"Error monitoring {item}: {e}")
    
    logger.info("Price monitoring completed")

async def check_news(context: ContextTypes.DEFAULT_TYPE):
    """Проверка новостей"""
    global news_cache
    
    logger.info("Checking for news...")
    
    try:
        news_items = await news_parser.get_steam_news()
        
        if not news_items:
            return
        
        new_news = []
        if news_cache:
            cached_titles = {item.get('title') for item in news_cache if 'title' in item}
            new_news = [item for item in news_items if item.get('title') not in cached_titles]
        else:
            new_news = news_items[:1]
        
        for item in news_items:
            item['fetched'] = datetime.now()
        news_cache = news_items
        
        for news_item in new_news:
            if news_item.get('impact') in ['🔥 Высокое', '⚠️ Среднее']:
                for user_id, data in list(user_data.items()):
                    if data.get('notifications'):
                        try:
                            message = f"📰 <b>Важная новость CS2!</b>\n\n"
                            message += f"<b>{news_item.get('title', 'Без названия')}</b>\n\n"
                            message += f"📅 {news_item.get('date', 'N/A')}\n"
                            message += f"Влияние: {news_item.get('impact', 'N/A')}"
                            
                            await context.bot.send_message(
                                chat_id=user_id,
                                text=message,
                                parse_mode='HTML'
                            )
                        except Exception as e:
                            logger.error(f"Error sending news to {user_id}: {e}")
        
        logger.info(f"Found {len(new_news)} new news items")
        
    except Exception as e:
        logger.error(f"Error checking news: {e}")

async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):
    """Ежедневный отчет"""
    logger.info("Sending daily reports...")
    
    for user_id, data in list(user_data.items()):
        if not data.get('notifications') or data.get('mode') == 'news':
            continue
        
        try:
            portfolio = data.get('portfolio', [])
            
            if not portfolio:
                continue
            
            text = "📊 <b>Ежедневный отчет</b>\n\n"
            total_value = 0.0
            growing = 0
            falling = 0
            
            for idx in portfolio:
                if idx >= len(POPULAR_ITEMS):
                    continue
                
                item = POPULAR_ITEMS[idx]
                price_data = await steam_api.get_item_price(item)
                
                if price_data:
                    trend = analyzer.detect_trend(item)
                    
                    if 'рост' in trend.lower():
                        growing += 1
                    elif 'падение' in trend.lower():
                        falling += 1
                    
                    try:
                        price_str = str(price_data.get('median_price', '$0')).replace(', '').replace(',', '')
                        total_value += float(price_str)
                    except (ValueError, AttributeError):
                        pass
                
                await asyncio.sleep(0.5)
            
            text += f"💼 <b>Портфель:</b> {len(portfolio)} предметов\n"
            text += f"💰 <b>Стоимость:</b> ${total_value:.2f}\n\n"
            text += f"📈 Растут: {growing}\n"
            text += f"📉 Падают: {falling}\n"
            text += f"➡️ Стабильны: {len(portfolio) - growing - falling}\n\n"
            
            if growing > falling:
                text += "✅ Хороший день! Портфель растет."
            elif falling > growing:
                text += "⚠️ Портфель снижается. Проверьте позиции."
            else:
                text += "➡️ Стабильный день на рынке."
            
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode='HTML'
            )
            
        except Exception as e:
            logger.error(f"Error sending report to {user_id}: {e}")
    
    logger.info("Daily reports sent")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ошибок"""
    logger.error(f"Update {update} caused error {context.error}")
    
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "❌ Произошла ошибка. Попробуйте позже или используйте /start"
            )
    except Exception as e:
        logger.error(f"Error in error_handler: {e}")

# ============================================================================
# ЗАПУСК БОТА
# ============================================================================

async def post_init(application: Application):
    """Действия после инициализации"""
    logger.info("Bot initialized successfully!")
    await steam_api.init_session()
    await news_parser.init_session()

async def post_shutdown(application: Application):
    """Действия при остановке"""
    logger.info("Shutting down...")
    await steam_api.close_session()
    await news_parser.close_session()

def main():
    """Главная функция"""
    
    if TELEGRAM_TOKEN == 'YOUR_TELEGRAM_BOT_TOKEN':
        print("=" * 60)
        print("❌ ОШИБКА: Не установлены токены!")
        print("=" * 60)
        print("\n📝 Создайте файл .env с содержимым:\n")
        print("TELEGRAM_BOT_TOKEN=ваш_токен_от_BotFather")
        print("STEAM_API_KEY=ваш_steam_api_ключ")
        print("\n📖 Инструкция:")
        print("1. Telegram Token: https://t.me/BotFather -> /newbot")
        print("2. Steam API Key: https://steamcommunity.com/dev/apikey")
        print("=" * 60)
        return
    
    try:
        application = Application.builder().token(TELEGRAM_TOKEN).build()
        
        # Обработчики команд
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("menu", menu))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("portfolio", portfolio_command))
        application.add_handler(CommandHandler("top", top_command))
        application.add_handler(CommandHandler("news", news_command))
        
        # Обработчик кнопок
        application.add_handler(CallbackQueryHandler(button_callback))
        
        # Обработчик ошибок
        application.add_error_handler(error_handler)
        
        # Фоновые задачи
        job_queue = application.job_queue
        
        # Мониторинг цен каждые 30 минут
        job_queue.run_repeating(monitor_prices, interval=PRICE_CHECK_INTERVAL, first=60)
        
        # Проверка новостей каждый час
        job_queue.run_repeating(check_news, interval=NEWS_CHECK_INTERVAL, first=120)
        
        # Ежедневный отчет в 9:00
        job_queue.run_daily(send_daily_report, time=time(hour=9, minute=0))
        
        # Хуки инициализации
        application.post_init = post_init
        application.post_shutdown = post_shutdown
        
        # Запуск
        print("=" * 60)
        print("🎮 CS2 Trading Bot успешно запущен!")
        print("=" * 60)
        print("✅ Мониторинг цен: каждые 30 минут")
        print("✅ Проверка новостей: каждый час")
        print("✅ Ежедневный отчет: 09:00")
        print("=" * 60)
        print("🤖 Бот работает... Нажмите Ctrl+C для остановки")
        print("=" * 60)
        
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"\n❌ Критическая ошибка: {e}")
        print("Проверьте токены и интернет-соединение")

if __name__ == '__main__':
    main()