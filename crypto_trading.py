from binance.client import Client
import logging
import math
import time
import os

#Logger setup
logger = logging.getLogger('crypto_trader_logger')
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
fh = logging.FileHandler('crypto_trading.log')
fh.setLevel(logging.DEBUG)
fh.setFormatter(formatter)
logger.addHandler(fh)

logger.info('Started')

#Add supported coin symbols here
supported_coin_list = supported_coin_list = [u'XLM', u'XRP', u'TRX', u'ICX', u'EOS', u'IOTA', u'ONT', u'QTUM', u'ETC', u'ADA', u'XMR', u'DASH', u'NEO', u'ATOM', u'DOGE', u'VET', u'BAT', u'OMG', u'BTT']

#Dictionary of coin dictionaries.
#Designated to keep track of the selling point for each coin with respect to all other coins.
coin_table = dict((coin_entry, dict((coin, 0) for coin in supported_coin_list if coin != coin_entry))
			for coin_entry in supported_coin_list)

class CryptoState():
    _backup_file = ".crypto_trading_backup"

    def __init__(self, current_coin):
        if current_coin == '':
        	if(os.path.isfile(self._backup_file)):
        		f = open(self._backup_file, "r")
        		coin = f.read()
        		f.close()
        		self.current_coin = coin
        	else:
        		print(current_coin)
        		self.current_coin = current_coin
        		f = open(self._backup_file, "w")
        		f.close()
        else:
        	self.current_coin = current_coin

    def __setattr__(self, name, value):
        if name == "current_coin":
        	with open(self._backup_file, "w") as backup_file:
        		backup_file.write(value)
        	self.__dict__[name] = value
        	return

#Pass the symbol of the currently held coin here when running script for the first time
g_state = CryptoState('')

def retry(howmany):
	def tryIt(func):
		def f(*args, **kwargs):
			time.sleep(20)
			attempts = 0
			while attempts < howmany:
				try:
					return func(*args, **kwargs)
				except:
					print("Failed to Buy/Sell. Trying Again.")
					attempts += 1
		return f
	return tryIt        

def get_market_ticker_price(client, ticker_symbol):
	'''
	Get ticker price of a specific coin
	'''
	for ticker in client.get_symbol_ticker():
   		if ticker[u'symbol'] == ticker_symbol:
   			return float(ticker[u'price'])
	return None

def get_currency_balance(client, currency_symbol):
	'''
	Get balance of a specific coin
	'''
	for currency_balance in client.get_account()[u'balances']:
		if currency_balance[u'asset'] == currency_symbol:
			return float(currency_balance[u'free'])
	return None

@retry(20)
def buy_alt(client, alt_symbol, crypto_symbol):
	'''
	Buy altcoin
	'''
	ticks = {}
	for filt in client.get_symbol_info(alt_symbol + crypto_symbol)['filters']:
		if filt['filterType'] == 'LOT_SIZE':
			ticks[alt_symbol] = filt['stepSize'].find('1') - 2
			break

	order_quantity = ((math.floor(get_currency_balance(client, crypto_symbol) * \
		10**ticks[alt_symbol] / get_market_ticker_price(client,alt_symbol+crypto_symbol))/float(10**ticks[alt_symbol])))

	#Try to buy until successful
	order = client.order_limit_buy(
		symbol = alt_symbol + crypto_symbol,
		quantity = order_quantity,
		price = get_market_ticker_price(client,alt_symbol+crypto_symbol)
	)

	stat = client.get_order(symbol = alt_symbol+crypto_symbol, orderId = order[u'orderId'])

	while stat[u'status'] != 'FILLED':
		stat = client.get_order(symbol = alt_symbol+crypto_symbol, orderId = order[u'orderId'])
		time.sleep(1)

	logger.info('Bought %s', alt_symbol)

	return order

@retry(20)
def sell_alt(client, alt_symbol, crypto_symbol):
	'''
	Sell altcoin
	'''
	ticks = {}
	for filt in client.get_symbol_info(alt_symbol + crypto_symbol)['filters']:
		if filt['filterType'] == 'LOT_SIZE':
			ticks[alt_symbol] = filt['stepSize'].find('1') - 2
			break

	order_quantity = (math.floor(get_currency_balance(client, alt_symbol) * \
		10**ticks[alt_symbol])/float(10**ticks[alt_symbol]))

	bal = get_currency_balance(client, alt_symbol)

	order = client.order_market_sell(
		symbol = alt_symbol + crypto_symbol,
		quantity = (order_quantity)
	)

	logger.info('order')
	logger.info(order)

	stat = client.get_order(symbol = alt_symbol+crypto_symbol, orderId = order[u'orderId'])
	logger.info(stat)
	while stat[u'status'] != 'FILLED':
		logger.info(stat)
		stat = client.get_order(symbol = alt_symbol+crypto_symbol, orderId = order[u'orderId'])
		time.sleep(1)

	newbal = get_currency_balance(client, alt_symbol)
	while(newbal >= bal):
		newbal = get_currency_balance(client, alt_symbol)

	logger.info('Sold {0}'.format(alt_symbol))

	return order

def transaction_through_tether(client, source_coin, dest_coin):
	'''
	Jump from the source coin to the destination coin through tether
	'''
	result = None
	while result is None:
		result = sell_alt(client, source_coin, 'USDT')
	result = None
	while result is None:
		result = buy_alt(client, dest_coin, 'USDT')
	global g_state
	g_state.current_coin = dest_coin
	update_trade_threshold(client)

def update_trade_threshold(client):
	'''
	Update all the coins with the threshold of buying the current held coin
	'''
	for coin_dict in coin_table.copy():
		coin_table[coin_dict][g_state.current_coin] = float(get_market_ticker_price(client, coin_dict + 'USDT'))/float(get_market_ticker_price(client, g_state.current_coin + 'USDT'))

def initialize_trade_thresholds(client):
	'''
	Initialize the buying threshold of all the coins for trading between them
	'''
	for coin_dict in coin_table.copy():
		for coin in supported_coin_list:
			if coin != coin_dict:
				coin_table[coin_dict][coin] = float(get_market_ticker_price(client, coin_dict + 'USDT'))/float(get_market_ticker_price(client, coin + 'USDT'))

def scout(client, transaction_fee = 0.01, multiplier = 2):
	'''
	Scout for potential jumps from the current coin to another coin
	'''
	for optional_coin in [coin for coin in coin_table[g_state.current_coin].copy() if coin != g_state.current_coin]:
		#Obtain (current coin)/(optional coin)
		coin_opt_coin_ratio = float(get_market_ticker_price(client, g_state.current_coin + 'USDT'))/float(get_market_ticker_price(client, optional_coin + 'USDT'))

		if (coin_opt_coin_ratio - transaction_fee * multiplier * coin_opt_coin_ratio) > coin_table[g_state.current_coin][optional_coin]:
			logger.info('Jumping from {0} to {1}'.format(g_state.current_coin, optional_coin))
			transaction_through_tether(client, g_state.current_coin, optional_coin)

def main():
	#Add API key here
	api_key = ''
	#Add API secret key here
	api_secret_key = ''

	client = Client(api_key, api_secret_key)

	initialize_trade_thresholds(client)

	while True:
		try:
			time.sleep(60)
			scout(client)
		except:
			logger.info('Error while scouting...')

if __name__ == "__main__":
	main()
