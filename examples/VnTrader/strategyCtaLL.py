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
from apscheduler.schedulers.background import BackgroundScheduler
import os
import winsound

########################################################################
class CtaLLStrategy(CtaTemplate):
    """网格交易策略"""
    className = 'CtaLLStrategy'
    author = u'Robin'
    STATUS_FINISHED = set([STATUS_REJECTED, STATUS_CANCELLED, STATUS_ALLTRADED])
    STATUS_UNFINISHED = set([STATUS_NOTTRADED, STATUS_PARTTRADED])
    STATUS_INVALID = set([STATUS_REJECTED, STATUS_CANCELLED])
    STATUS_VALID = set([STATUS_NOTTRADED, STATUS_PARTTRADED,STATUS_ALLTRADED])

    # 策略变量
    price_grid = [] # [453.00 + i* 10.0  for i in range(0,10)]
    control_dict = {}
    PROFIT = 15.00
    TICK_COUNTER = 100
    tick_number = 0
    dbClient = None
    scheduler = None    # background scheduler for daily routine task

    # 参数列表，保存了参数的名称
    paramList = ['name',
                 'className',
                 'author',
                 'vtSymbol']

    # 变量列表，保存了变量的名称
    varList = ['inited',
               'trading',
               'price_grid',
               'control_dict'
             ]

    # 同步列表，保存了需要保存到数据库的变量名称
    syncList = ['price_grid',
                'control_dict'
              ]

    #----------------------------------------------------------------------
    def __init__(self, ctaEngine, setting):
        """Constructor"""
        super(CtaLLStrategy, self).__init__(ctaEngine, setting)
        self.am = ArrayManager()

        self.price_grid = [str(453 + i * 10) for i in range(0, 10)]
        self.tick_number = self.TICK_COUNTER #each X ticks, call tick_rebalance
        for grid in self.price_grid:
             self.control_dict[grid] = { 'buy_id': "", 'position': 0, 'sell_id': ""}

        #print "__init__"

        # 注意策略类中的可变对象属性（通常是list和dict等），在策略初始化时需要重新创建，
        # 否则会出现多个策略实例之间数据共享的情况，有可能导致潜在的策略逻辑错误风险，
        # 策略类中的这些可变对象属性可以选择不写，全都放在__init__下面，写主要是为了阅读
        # 策略时方便（更多是个编程习惯的选择）

    def onInit(self):
        """初始化策略（必须由用户继承实现）"""
        self.writeCtaLog(u'策略初始化')

        self.init_database()
        self.scheduler = BackgroundScheduler()  # init the scheduler
        self.scheduler.add_job(self.new_day_operation, 'cron', day_of_week='mon-fri', hour=8, minute=55)
        self.scheduler.add_job(self.close_day_operation, 'cron', day_of_week='mon-fri', hour=23, minute=31)
        self.scheduler.start()  # start scheduler for new_day_operation
        self.putEvent()

    # ----------------------------------------------------------------------
    def init_database(self):
        """连接MongoDB数据库"""
        if not self.dbClient:
            # 读取MongoDB的设置
            try:
                # 设置MongoDB操作的超时时间为0.5秒
                self.dbClient = MongoClient(globalSetting['mongoHost'], globalSetting['mongoPort'])
                # 调用server_info查询服务器状态，防止服务器异常并未连接成功
                self.dbClient.server_info()
                print "strategyCtaLL::init_database:" + text.DATABASE_CONNECTING_COMPLETED

            except ConnectionFailure:
                print "strategyCtaLL::init_database:" + text.DATABASE_CONNECTING_FAILED

    #----------------------------------------------------------------------
    def onStart(self):
        """启动策略（必须由用户继承实现）"""
        #self.writeCtaLog(u'Demo演示策略启动')
        self.trading = True
        self.removeOldOrder()
        self.syncWithOrderDB()  # sync the control_dict with database
        self.putEvent()
        self.writeCtaLog(str(self.get_dense_control_dict()))

    #----------------------------------------------------------------------
    def onStop(self):
        """停止策略"""
#        self.scheduler.shutdown() # end scheduler for new_day_operation
        self.trading = False
        if self.is_Trading_Slot():
            self.cancelAll()

        self.syncWithOrderDB()
        # 同步数据到数据库
        self.saveSyncData()
        self.putEvent()

    #----------------------------------------------------------------------
    def onTick(self, tick):
        """收到行情TICK推送（必须由用户继承实现）"""
#        self.writeCtaLog('onTick')
        if not self.inited or not self.trading or not self.is_Trading_Slot():  # strategy not inited or not started
            # print ("onTick::策略未初始化/未启动/非交易时段，不处理tick信息{}")
            return

        self.tick_number -= 1

        # 确保策略每X个TICK执行一次
        if self.tick_number == 0:
            self.tick_number = self.TICK_COUNTER
            print ("onTick::每收到{}个TICK,再平衡仓位...@{}".format(self.TICK_COUNTER, tick.time))
            self.tick_rebalance(tick) #  以什么价格tick.askprice1买进

        # print ("onTick::同步数据到数据库")
        self.putEvent()

    # ----------------------------------------------------------------------
    def tick_rebalance(self,tick):
        """根据最新价格调整仓位"""
        for grid,record in self.control_dict.items():
            vtOrderIDList = []
            sellPrice = float(grid) + self.PROFIT
            if record["position"] > 0 and sellPrice < tick.upperLimit and record['sell_id']=="": # has position
                """如网格有仓位无卖单，网格价+利润（15）挂卖单"""
                vtOrderIDList = self.sell(sellPrice,record["position"])
                if vtOrderIDList:
                    record['sell_id'] = vtOrderIDList[0]
                    print ('tick_rebalance：发卖单control_dict[{}]:{}'.format(grid, self.control_dict[grid]))
            elif tick.lowerLimit < int(grid) < tick.upperLimit and record["position"] == 0 and record['buy_id'] == "":
                """如网格在涨跌停价之间，无对应仓位及买单，以现价或网格价（选低价）挂买单"""
                buyPrice = min(int(grid),tick.askPrice1)
                vtOrderIDList = self.buy(buyPrice, 1)
                if vtOrderIDList:
                    record['buy_id'] =  vtOrderIDList[0]
                    print ('tick_rebalance：发买单control_dict[{}]:{}'.format(grid, self.control_dict[grid]))

        # 同步数据到数据库
        self.saveSyncData()

    # ----------------------------------------------------------------------
    def onOrder(self, order):
        """收到委托变化推送（必须由用户继承实现）"""
        print ( "onOrder::{}".format(order.__dict__))

        found = False
        for grid, record in self.control_dict.items():
            if order.vtOrderID == record["buy_id"]:
                found = True
                if order.status in self.STATUS_INVALID:  # 订单无效，清空订单价格和ID  STATUS_FINISHED[STATUS_REJECTED, STATUS_CANCELLED, STATUS_ALLTRADED]
                # STATUS_ALLTRADED 控制表订单项不置空，是因为后续ONTRADE需要该信息
                    record["buy_id"] = ""
            elif order.vtOrderID == record["sell_id"]:
                found = True
                if order.status in self.STATUS_INVALID:
                    record["sell_id"] = ""

        if found == False:
            print "onOrder::ERROR 订单不在控制表中，请仔细核对:{}\n 订单:{}".format(self.get_dense_control_dict(), repr(order.__dict__).decode('unicode-escape'))
            return

        # 同步数据到数据库
        self.saveSyncData()
        print ("onOrder::同步数据到数据库")
        self.putEvent()


    # ----------------------------------------------------------------------
    def onPositionEvent(self, position):  #event,
        """收到仓位信息推送.确保策略开始时，仓位为空.本消息仅做仓位审查,不做仓位平衡处理"""
        # self.writeCtaLog("onPositionEvent::position:{}".format(position))
        self.pos = position.position

        if not self.inited or not self.trading:  # strategy not inited or not started
           # print ("onPositionEvent::策略未初始化/未启动，不处理position信息")
            return

        total_position = 0
        for grid, record in self.control_dict.items():
            total_position+=record['position']

        if total_position != position.position:
            print ("WARNNING!onPositionEvent:控制表仓位{}与实际仓位{}不匹配，请核对。\t{}".format
                   (total_position, position.position, self.get_dense_control_dict()))
        #     if total_position > position.position:#控制表仓位大于实际仓位
        #         self.onStop()
        #         self.writeCtaLog("ERROR:控制表仓位大于与实际仓位，停止策略！")
        #     elif position.position> total_position:
        #         if self.is_Trading_Time():
        #             print "Warnning:实际仓位大于控制表仓位，卖出！"
        #             vtOrderIDList = self.sell(self.lastTick.bidPrice1,position.position - total_position)  # 清空不匹配仓位 TODO 如何判断是否在交易时段,bidPrice1是有效的
        #         else:
        #             print "onPositionEvent:非交易时段，不进行仓位调整"

    #----------------------------------------------------------------------
    def onTrade(self, trade):
        self.writeCtaLog("onTrade::成交确认{}".format(trade.__dict__))
        winsound.Beep(2500, 1000)
        # -----------------------------------------------------------------------------------
        # 更新网格仓位字典
        found = False
        for grid, record in self.control_dict.items():
            if trade.direction == DIRECTION_LONG: # 买单
                if trade.vtOrderID == record["buy_id"]:
                    record["buy_id"] = ""
                    found = True
                    print "onTrade::网格{}买单{}以价格{}买入{} 之前持仓：{}".format(grid, trade.vtOrderID, trade.price, trade.volume,record["position"])
                    record["position"] += trade.volume
                    print "onTrade::网格{}买单{}以价格{}买入{} 之后持仓：{}".format(grid, trade.vtOrderID, trade.price, trade.volume,record["position"])
                    break
            elif trade.direction == DIRECTION_SHORT:  # CTAORDER_SELL:
                if trade.vtOrderID == record["sell_id"]:
                    record["sell_id"]=""
                    found = True
                    print "onTrade::网格{}卖单{}以价格{}卖出{} 之前持仓：{}".format(grid, trade.vtOrderID, trade.price, trade.volume,record["position"])
                    if record["position"] >= trade.volume:
                        record["position"] -= trade.volume
                        print "onTrade::网格{}卖单{}以价格{}卖出{} 之后持仓：{}".format(grid, trade.vtOrderID, trade.price,trade.volume, record["position"])
                        break

        if found == False:
#            self.onStop()
            print "onTrade::ERROR 成交不在控制表中，请仔细核对:{}\n 成交:{}".format(self.control_dict,repr(trade.__dict__).decode('unicode-escape'))
            return
        # -----------------------------------------------------------------------------------
        # 同步数据到数据库   ？这步多余？ processTradeEvent in ctaEngine.py has the same operation
        self.saveSyncData()
        print ("onTrade::同步数据到数据库")
        # 发出状态更新事件
        self.putEvent()

    #----------------------------------------------------------------------
    def onStopOrder(self, so):
        """停止单推送"""
        pass

    #----------------------------------------------------------------------
    def is_Trading_Time(self,now=None): #当前是否在交易时段
        if not now:
            now = datetime.now()
        now_workday = now.weekday()   #wrong!need to check the tick date
        now_time = now.time()
        if now_workday < 5 \
            and (time(9,0)< now_time < time(10,15) or time(10,30)< now_time < time(11,30) \
            or time(13,30)< now_time < time(15,30) or time(21,0)< now_time < time(23,30) ):
            return True
        else:
            return False

    #----------------------------------------------------------------------
    def is_Trading_Slot(self,now=None):#是否在开盘和收盘时间之间
        if not now:
            now = datetime.now()
        now_workday = now.weekday()   #wrong!need to check the tick date
        now_time = now.time()
        if now_workday < 5 and (time(9,0)< now_time < time(23,30)):
            return True
        else:
            return False

    # ----------------------------------------------------------------------
    def cancelAll(self):
         print "cancelAll::取消所有委托"
         for grid, record in self.control_dict.items():
             if record['buy_id']!="":
                 vtOrderID = record['buy_id']
                 print ("cancelAll::取消网格{}处买单{}".format(grid,vtOrderID))
                 if STOPORDERPREFIX in vtOrderID:
                     self.ctaEngine.cancelStopOrder(vtOrderID)
                 else:
                     self.ctaEngine.cancelOrder(vtOrderID)
             elif record['sell_id']!="":
                 vtOrderID = record['sell_id']
                 self.writeCtaLog("cancelAll::取消网格{}处卖单{}".format(grid,vtOrderID))
                 if STOPORDERPREFIX in vtOrderID:
                      self.ctaEngine.cancelStopOrder(vtOrderID)
                 else:
                    self.ctaEngine.cancelOrder(vtOrderID)

         self.putEvent()
    # ----------------------------------------------------------------------
    def syncWithOrderDB(self):
        """把控制表状态和订单数据库同步，在策略启动和停止的时候调用？"""
        print "syncWithOrderDB:把控制表状态和订单数据库同步，在策略启动和停止的时候调用"
        for grid, record in self.control_dict.items():
            if record['buy_id'] != "":
                cursor = self.ctaEngine.loadOrderByID(record['buy_id'])
                if not cursor:# no order find in the Order database
                    #print "syncWithOrderDB:no order found,reset buy_id {} at grid {} to empty".format(record['buy_id'],grid)
                    record['buy_id'] = ""
                elif len(cursor) == 1 and cursor[0]["status"] in self.STATUS_FINISHED:
                    #print "syncWithOrderDB:order finished,reset buy_id {} at grid {} to empty".format(record['buy_id'],grid)
                    record['buy_id'] = ""
                elif len(cursor) > 1:
                    print "syncWithOrderDB:multiple id {} in database at grid {}".format(record['buy_id'],grid)
            elif record['sell_id'] != "":
                cursor = self.ctaEngine.loadOrderByID(record['sell_id'])
                if not cursor:
                    #print "syncWithOrderDB:no order found,reset sell_id {} at grid {} to empty".format(record['sell_id'],grid)
                    record['sell_id'] = ""
                elif len(cursor) == 1 and cursor[0]["status"] in self.STATUS_FINISHED:
                    #print "syncWithOrderDB:order finished,reset sell_id {} at grid {} to empty".format(record['sell_id'],grid)
                    record['sell_id'] = ""
                elif len(cursor) > 1:
                    print "syncWithOrderDB:multiple id {} in database at grid {}".format(record['sell_id'], grid)

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
    def removeOldOrder(self):
        """清除订单数据库非当日订单"""
        db = self.dbClient[POSITION_DB_NAME]
        collection = db[ORDER_COL_NAME]
        dt = str(datetime.now().date())
        flt = {'updateTime': {'$ne': dt}}
        result = collection.delete_many(flt)

        print "strategyCtaLL::removeOldOrder: 清除订单数据库非当日{}订单,结果:{}".format(dt,result.__dict__)

    # ----------------------------------------------------------------------
    def no_activated_order(self):
        """控制表中无有效订单"""
        for grid, record in self.control_dict.items():
            if record['buy_id']!="" or record['sell_id']!="":
                return False

        return True

    # ----------------------------------------------------------------------
    def onInstrument(self,instrument):
        #print "onInstrument::",instrument
        pass

    # ----------------------------------------------------------------------
    def onAccountEvent(self,  account):  #event,
        pass
        """收到账号信息推送"""

    # ----------------------------------------------------------------------
    def get_dense_control_dict(self):
        dense_control_dict = {}
        for grid, record in self.control_dict.items():
            if record['buy_id']!="" or record['sell_id']!="" or record['position']!= 0:
                dense_control_dict[grid] = record

        return dense_control_dict





    # # ----------------------------------------------------------------------
    #
    # def getOrderTable(self):
    #     result = self.ctaEngine.loadOrderByStatus(self.STATUS_FINISHED)
    #     print "strategyCtaLL:getOrderTable" + repr(result).decode("unicode-escape")
    #     print "strategyCtaLL:getOrderTable result length {}".format(len(result))
    # # ----------------------------------------------------------------------
    # def getOrderByDate(self, dt = None):
    #     result = self.ctaEngine.loadOrderByDate(dt)
    #     print "strategyCtaLL:getOrderByDate" + repr(result).decode("unicode-escape")
    #     print "strategyCtaLL:getOrderByDate result length {}".format(len(result))
    # #----------------------------------------------------------------------
    # def onBar(self, bar):
    #     """收到Bar推送（必须由用户继承实现）"""
    #     self.writeCtaLog('onBar')
    #     #self.bm.updateBar(bar)
    #     am = self.am
    #     am.updateBar(bar)

    # ----------------------------------------------------------------------
    # def init_position(self, tick):
    #     """初始化仓位"""
    #     self.writeCtaLog('init_position：当前仓位：{},初始化仓位'.format(self.pos))
    #
    #     # 填满现价以上的网格
    #     grids = [str(i) for i in self.price_grid if int(i) > tick.askPrice1]
    #     for grid in grids:
    #         if self.control_dict[grid]['buy_id'] == "" and self.control_dict[grid]['position'] == 0:  # always make sure no conflict order on same grid
    #             vtOrderIDList = self.buy(tick.askPrice1, 1)  # TODO, 如果未成交该如何处理
    #             if vtOrderIDList:
    #                 self.control_dict[grid]['buy_id'] =  vtOrderIDList[0]
    #                 print ('init_position：control_dict[{}]:{}'.format(grid,self.control_dict[grid]))