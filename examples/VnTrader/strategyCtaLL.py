# encoding: UTF-8

"""
一个ATR-RSI指标结合的交易策略，适合用在股指的1分钟和5分钟线上。

注意事项：
1. 作者不对交易盈利做任何保证，策略代码仅供参考
2. 本策略需要用到talib，没有安装的用户请先参考www.vnpy.org上的教程安装
3. 将IF0000_1min.csv用ctaHistoryData.py导入MongoDB后，直接运行本文件即可回测策略

"""

from vnpy.trader.vtObject import VtBarData
from vnpy.trader.vtConstant import *
# EMPTY_STRING,
#                                     DIRECTION_LONG,
#                                     DIRECTION_SHORT,
#                                     STATUS_NOTTRADED,
#                                     STATUS_REJECTED,
#                                     STATUS_CANCELLED,
#                                     STATUS_ALLTRADED,
#                                     STATUS_PARTTRADED
from vnpy.trader.app.ctaStrategy.ctaTemplate import (CtaTemplate,
                                                     BarManager,
                                                     ArrayManager)
from vnpy.trader.app.ctaStrategy.ctaBase import *
from datetime import datetime, time
from time import sleep
import json
from pymongo import MongoClient, ASCENDING
from pymongo.errors import ConnectionFailure
from vnpy.trader.vtGlobal import globalSetting
from vnpy.trader.language import text
#from apscheduler.schedulers.background import BackgroundScheduler
import os
import winsound
from pprint import pprint,pformat
from msg_my import init_mail_server, send_email
import itchat  # for sending wechat msg

########################################################################
class CtaLLStrategy(CtaTemplate):
    """网格交易策略"""
    className = 'CtaLLStrategy'
    author = u'Robin'

    POS_PER_GRID = 2 #每网格对应的仓位

    # 策略变量
    price_grid = [] # [453.00 + i* 10.0  for i in range(0,10)]
    control_dict = {}
    PROFIT = 15.00
    START2SHORT = 550.00 #此价格以上的网格点可开空单
    TICK_COUNTER = 100
    tick_number = 0

    #scheduler = None    # background scheduler for daily routine task
    lower_limit = 0.0
    upper_limit = 0.0

    # 参数列表，保存了参数的名称
    paramList = ['name',
                 'className',
                 'author',
                 'vtSymbol']

    # 变量列表，保存了变量的名称
    varList = ['inited',
               'trading',
               'price_grid',
               'control_dict',
               'lower_limit',
               'upper_limit'
             ]

    # 同步列表，保存了需要保存到数据库的变量名称
    syncList = ['price_grid',
                'control_dict'
              ]
    mailServer = None
    friends = []
    wechat_flag = False


    #----------------------------------------------------------------------
    def __init__(self, ctaEngine, setting):
        """Constructor"""
        super(CtaLLStrategy, self).__init__(ctaEngine, setting)
        self.am = ArrayManager()

        #self.price_grid = [str(453 + i * 10) for i in range(0, 10)]
        self.price_grid = [str(453 + i * 10) for i in range(0, 15)]
        self.tick_number = self.TICK_COUNTER #each X ticks, call tick_rebalance
        for grid in self.price_grid:
             self.control_dict[grid] = { 'buy_id': "", 'position': 0, 'sell_id': ""}

        self.last_tick = None # 保存上个TICK
        self.wechat_flag = False
        #print "__init__"

        # 注意策略类中的可变对象属性（通常是list和dict等），在策略初始化时需要重新创建，
        # 否则会出现多个策略实例之间数据共享的情况，有可能导致潜在的策略逻辑错误风险，
        # 策略类中的这些可变对象属性可以选择不写，全都放在__init__下面，写主要是为了阅读
        # 策略时方便（更多是个编程习惯的选择）

    def onInit(self):
        """初始化策略（必须由用户继承实现）"""
        self.writeCtaLog(u'策略初始化')

        #self.scheduler = BackgroundScheduler()  # init the scheduler

        self.putEvent()

    #----------------------------------------------------------------------
    def onStart(self):
        """启动策略（必须由用户继承实现）"""
        #self.writeCtaLog(u'Demo演示策略启动')
        self.trading = True
        self.putEvent()
        self.get_dense_control_dict(True)
        # # 初始化邮件服务
        # self.mailServer = init_mail_server()
        # send_email(self.mailServer,
        #     '当前网格\n{}'.format(pformat(self.get_dense_control_dict(), indent=4)),
        #     "策略启动@{}".format(datetime.now().time()))

        # 初始化微信服务
        # if self.wechat_flag:
        if not itchat.instanceList[0].alive:
            itchat.auto_login(hotReload=True)

        if itchat.instanceList[0].alive:
            self.friends = itchat.get_friends(update=True)
            self.send_wechat_msg(u'策略启动', u'管刚')
            '''发送微信消息'''  # u'管刚' # u'Jane洁'

        #添加预定任务
        # self.scheduler.add_job(self.onStop, 'cron', day_of_week='mon-fri', hour=14, minute=59)
        # self.scheduler.add_job(self.onStop, 'cron', day_of_week='mon-fri', hour=23, minute=29)
        # self.scheduler.start()  # start scheduler for new_day_operation

        # ----------------------------------------------------------------------
    def new_day_init(self,dt = None):
        """新交易日初始化"""
        self.writeCtaLog(u"新交易日初始化")
        self.cancelAll()
        self.tick_number = self.TICK_COUNTER  # each X ticks, call tick_rebalance
        sleep(10)
        self.syncWithOrderDict()
    #----------------------------------------------------------------------
    def onStop(self):
        """停止策略"""
        # TODO WORKAROUND: 11:29调用，取消所有夜盘订单
        self.trading = False
        self.cancelAll()    #stopStrategy of ctaEngine will call cancelAll then call onStop of strategy
        sleep(10)
        self.syncWithOrderDict()
        # 同步数据到数据库
        self.saveSyncData()
        self.putEvent()
        # #关闭邮件服务
        # self.mailServer.close()
        # #关闭微信服务
        self.send_wechat_msg(u'策略关闭', u'管刚')
        # itchat.logout()
        # 清空所有预定任务
        # self.scheduler.remove_all_jobs()

    #----------------------------------------------------------------------
    def send_wechat_msg(self,msg,name):
        '''发送微信消息''' # u'管刚' # u'Jane洁'
        if not itchat.instanceList[0].alive:
            return

        for friend in self.friends:
            if name in friend['NickName']:
                itchat.send(u'机器人消息：'+ msg,toUserName=friend['UserName'])

    #----------------------------------------------------------------------
    def onTick(self, tick):
        """收到行情TICK推送"""
        # print "收到行情TICK推送"
        if not self.inited or not self.trading:# or not self.is_Trading_Slot():  # strategy not inited or not started
            #print ("onTick::策略未初始化/未启动不处理tick信息{}")
            return

        if self.last_tick == None:
            self.last_tick = tick
            self.new_day_init(tick.date) # 策略初次运行，收到第一个TICK，做必要初始化
            print "第一个TICK，初始化,date:{}".format(tick.date)
            return
        elif self.last_tick.__dict__ == tick.__dict__:   # 如果tick内容一样，略去
            self.last_tick = tick
            print "重复TICK，略去"
            return

        if tick.date > self.last_tick.date: # 日期变大
            self.new_day_init(tick.date)

        self.last_tick = tick
        self.tick_number -= 1

        # 确保策略每X个TICK执行一次
        if self.tick_number == 0:
            self.tick_number = self.TICK_COUNTER
            self.lower_limit = tick.lowerLimit
            self.upper_limit = tick.upperLimit
            self.writeCtaLog( "onTick::每收到{}个TICK,再平衡仓位...@{},涨停{}跌停{} 最新价{}".format(self.TICK_COUNTER, tick.time, self.upper_limit,self.lower_limit, tick.lastPrice))
            #self.tick_rebalance(tick) #  以什么价格tick.askprice1买进
            self.rebalance(tick)

        # print ("onTick::同步数据到数据库")
        self.putEvent()

    # ----------------------------------------------------------------------
    def rebalance(self,tick):
        """根据最新价格调整仓位,加入支持空单"""
        for grid,record in self.control_dict.items():
            vtOrderIDList = []
            if int(grid) < self.START2SHORT:
                # print "网格点:{} 位于多区[453,463....533,543]".format(grid)
                if record['position'] == 0 and record['buy_id'] == "":
                    """无仓位，无对应BUY单，以现价或网格价（选低价，且价格在涨跌停之间）挂BUY单"""
                    buyPrice = min(int(grid), tick.askPrice1)
                    if tick.lowerLimit < buyPrice < tick.upperLimit:
                        vtOrderIDList = self.buy(buyPrice, self.POS_PER_GRID)
                        if vtOrderIDList:
                            record['buy_id'] = vtOrderIDList[0]
                            msg = u'rebalance：发buy单control_dict[{}]:{}@{}'.format(grid, self.control_dict[grid],buyPrice)
                            self.writeCtaLog(msg)
                            self.send_wechat_msg(msg, u'管刚')
                elif record["position"] > 0 and record['sell_id']=="":
                    """如网格有仓位无SELL单，以网格价+利润或现价（选高价，且价格在涨跌停之间）挂SELL单"""
                    sellPrice = max(float(grid) + self.PROFIT,tick.bidPrice1)
                    if tick.lowerLimit < sellPrice < tick.upperLimit:
                        vtOrderIDList = self.sell(sellPrice, record["position"])
                        if vtOrderIDList:
                            record['sell_id'] = vtOrderIDList[0]
                            msg = u'rebalance：发sell单control_dict[{}]:{}@{}'.format(grid, self.control_dict[grid],sellPrice)
                            self.writeCtaLog(msg)
                            self.send_wechat_msg(msg, u'管刚')
            elif int(grid) > self.START2SHORT:
                # print "网格点:{} 位于空区[553,563,573,583,593]".format(grid)
                if record['position'] == 0 and record['sell_id'] == "":
                    """无仓位，无对应SHORT单，以现价或网格价（选高价，且价格在涨跌停之间）挂SHORT单"""
                    shortPrice = max(int(grid),tick.bidPrice1)
                    if tick.lowerLimit < shortPrice < tick.upperLimit:
                        vtOrderIDList = self.short(shortPrice, self.POS_PER_GRID)
                        if vtOrderIDList:
                            record['sell_id'] = vtOrderIDList[0]
                            msg = u'rebalance：发short单control_dict[{}]:{}@{}'.format(grid, self.control_dict[grid],shortPrice)
                            self.writeCtaLog(msg)
                            self.send_wechat_msg(msg, u'管刚')
                elif record["position"] > 0 and record['buy_id']=="":
                    """如网格有空仓无COVER单，以网格价-利润或现价（选低价，且价格在涨跌停之间）挂COVER单"""
                    coverPrice = min(int(grid) - self.PROFIT, tick.askPrice1)
                    if tick.lowerLimit < coverPrice < tick.upperLimit:
                        vtOrderIDList = self.cover(coverPrice, record['position'])
                        if vtOrderIDList:
                            record['buy_id'] = vtOrderIDList[0]
                            msg = u'rebalance：发cover单control_dict[{}]:{}@{}'.format(grid, self.control_dict[grid],coverPrice)
                            self.writeCtaLog(msg)
                            self.send_wechat_msg(msg, u'管刚')

        # 同步数据到数据库
        self.get_dense_control_dict(False)
        self.saveSyncData()


        # ----------------------------------------------------------------------
    def onOrder(self, order):
        """收到委托变化推送（必须由用户继承实现）"""
        self.writeCtaLog ( "onOrder::{}".format(repr(order.__dict__)).decode('unicode-escape'))

        found = False
        for grid, record in self.control_dict.items():
            if order.vtOrderID == record["buy_id"]:
                found = True
                if order.status == STATUS_REJECTED or order.status ==  STATUS_CANCELLED:
                    record["buy_id"] = ""
                elif order.status == STATUS_PARTTRADED:
                    record["position"] = order.tradedVolume
                elif order.status == STATUS_ALLTRADED:
                    record["position"] = order.tradedVolume
                    record["buy_id"] = ""
            elif order.vtOrderID == record["sell_id"]:
                found = True
                if order.status == STATUS_REJECTED or order.status ==  STATUS_CANCELLED:
                    record["sell_id"] = ""
                elif order.status == STATUS_PARTTRADED:
                    record["position"] -= order.tradedVolume
                elif order.status == STATUS_ALLTRADED:
                    record["position"] = 0
                    record["buy_id"] = ""

        if found == False:
            self.writeCtaLog("onOrder::ERROR 订单不在控制表中，请仔细核对:{}\n 订单:{}".format(self.get_dense_control_dict(), repr(order.__dict__).decode('unicode-escape')))
            return

        # 同步数据到数据库
        self.saveSyncData()
        self.writeCtaLog("onOrder::同步数据到数据库")
        self.putEvent()

        # 如出现订单被拒的情况，停止策略
        if order.status == STATUS_REJECTED:
            msg = u"ERROR 订单被拒，停止策略".format(order.vtOrderID)
            self.send_wechat_msg(msg, u'管刚')
            self.writeCtaLog(msg)
            self.onStop()
            winsound.Beep(2500, 1000)
            return

    # ----------------------------------------------------------------------
    def onPositionEvent(self, position):  #event,
        """收到仓位信息推送.确保策略开始时，仓位为空.本消息仅做仓位审查,不做仓位平衡处理"""
        pass

    #----------------------------------------------------------------------
    def onTrade(self, trade):
        '''onTrade 提醒及发布状态更新'''
        self.writeCtaLog("onTrade::成交确认{}".format(trade.__dict__))
        wechat_msg = u'成交确认:订单[{}] 价格[{}] 方向[{}] 成交{}手'.format(trade.vtOrderID, trade.price, trade.direction, trade.volume)
        self.send_wechat_msg(wechat_msg, u'管刚')
        winsound.Beep(2500, 1000)
#       send_email()
#
#         # 更新网格仓位字典
#         found = False
#         for grid, record in self.control_dict.items():
#             if trade.direction == DIRECTION_LONG: # 买单
#                 if trade.vtOrderID == record["buy_id"]:
#                     record["buy_id"] = ""    # todo 部分成交的时候，不能清空
#                     found = True
#                     self.writeCtaLog("onTrade::网格{}买单{}以价格{}买入{} 之前持仓：{}".format(grid, trade.vtOrderID, trade.price, trade.volume,record["position"]))
#                     record["position"] += trade.volume
#                     self.writeCtaLog("onTrade::网格{}买单{}以价格{}买入{} 之后持仓：{}".format(grid, trade.vtOrderID, trade.price, trade.volume,record["position"]))
#                     break
#             elif trade.direction == DIRECTION_SHORT:  # CTAORDER_SELL:
#                 if trade.vtOrderID == record["sell_id"]:
#                     record["sell_id"]="" # todo 部分成交的时候，不能清空
#                     found = True
#                     self.writeCtaLog("onTrade::网格{}卖单{}以价格{}卖出{} 之前持仓：{}".format(grid, trade.vtOrderID, trade.price, trade.volume,record["position"]))
#                     if record["position"] >= trade.volume:
#                         record["position"] -= trade.volume
#                         self.writeCtaLog("onTrade::网格{}卖单{}以价格{}卖出{} 之后持仓：{}".format(grid, trade.vtOrderID, trade.price,trade.volume, record["position"]))
#                         break
#
#         if found == False:
# #            self.onStop()
#             self.writeCtaLog("onTrade::ERROR 成交不在控制表中，请仔细核对:{}\n 成交:{}".format(self.control_dict,repr(trade.__dict__).decode('unicode-escape')))
#             return
#         # -----------------------------------------------------------------------------------
#         # 同步数据到数据库   ？这步多余？ processTradeEvent in ctaEngine.py has the same operation
#         self.saveSyncData()
#         # 发出状态更新事件
#         self.putEvent()
#
#         # send_email(self.mailServer,
#         #            '当前网格\n{}'.format(pformat(self.get_dense_control_dict(), indent=4)),
#         #            '成交确认:订单[{}] 价格[{}] 方向[{}] 成交{}手'.format(trade.vtOrderID, trade.price, trade.direction, trade.volume)
#         #            )

    #----------------------------------------------------------------------
    def onStopOrder(self, so):
        """停止单推送"""
        pass


    # ----------------------------------------------------------------------
    def syncWithOrderDict(self):
        """把控制表状态和订单数据库同步，在策略启动和停止的时候调用？"""
        self.writeCtaLog("syncWithOrderDict:把控制表状态和订单字典同步，在策略启动和新交易日的时候调用")
        self.get_dense_control_dict(True)
        self.writeCtaLog("strategyOrderDict[{}]:{}".format(self.name,self.ctaEngine.strategyOrderDict[self.name]))
        for grid, record in self.control_dict.items():
            if record['buy_id'] != "":
                if record['buy_id'] not in self.ctaEngine.strategyOrderDict[self.name]:# no order find in the Order database
                    self.ctaEngine.cancelOrder(record['buy_id'])
                    self.writeCtaLog('buy order:{} not in strategyOrderDict,cancelling....'.format(record['buy_id']))
                    record['buy_id'] = ""
            elif record['sell_id'] != "":
                if record['sell_id'] not in self.ctaEngine.strategyOrderDict[self.name]:
                    self.ctaEngine.cancelOrder(record['sell_id'])
                    self.writeCtaLog('sell order:{} not in strategyOrderDict,cancelling....'.format(record['sell_id']))
                    record['sell_id'] = ""

        self.saveSyncData()

    # ----------------------------------------------------------------------
    def new_day_operation(self):
        """交易日开始"""
        print "交易日开始++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++"

        if self.trading == False:
            self.onStart()

    # ----------------------------------------------------------------------
    def close_day_operation(self):
        """交易日开始"""
        print "交易日结束++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++"

        if self.trading == True:
            self.onStop()

    # ----------------------------------------------------------------------
    def onInstrument(self,instrument):
        #print "onInstrument::",instrument
        pass

    # ----------------------------------------------------------------------
    def onAccountEvent(self,  account):  #event,
        pass
        """收到账号信息推送"""

    # ----------------------------------------------------------------------
    def get_dense_control_dict(self,print_flag = False):
        dense_control_dict = {}
        for grid, record in self.control_dict.items():
            if record['buy_id']!="" or record['sell_id']!="" or record['position']!= 0:
                dense_control_dict[grid] = record

        if print_flag:
            print "当前网格控制表："
            pprint(dense_control_dict)

        return dense_control_dict
