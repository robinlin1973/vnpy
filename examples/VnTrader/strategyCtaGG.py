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

import bisect
from datetime import datetime, time
import os
import csv
from time import sleep
import json


########################################################################
class CtaGGStrategy(CtaTemplate):
    """网格交易策略"""
    className = 'CtaGGStrategy'
    author = u'Robin'
    STATUS_FINISHED = set([STATUS_REJECTED, STATUS_CANCELLED, STATUS_ALLTRADED])
    STATUS_UNFINISHED = set([STATUS_NOTTRADED, STATUS_PARTTRADED])

    # 策略变量
    startPrice = 0.0
    endPrice = 0.0
    priceGrid = [] # [453.00 + i* 10.0  for i in range(0,10)]
    posGrid = {}
    profit = 0.00
    lastClose = 0.0 # the close price in previous bar
    bNewDay = True
    orderList = []


    # 参数列表，保存了参数的名称
    paramList = ['name',
                 'className',
                 'author',
                 'vtSymbol']

    # 变量列表，保存了变量的名称
    varList = ['inited',
               'trading',
               'startPrice',
               'endPrice',
               'price_grid',
               'posGrid',
               'PROFIT',
               'orderList'
             ]

    # 同步列表，保存了需要保存到数据库的变量名称
    syncList = ['startPrice',
                'endPrice',
                'price_grid',
                'posGrid',
                'PROFIT',
                'orderList'
              ]

    #----------------------------------------------------------------------
    def __init__(self, ctaEngine, setting):
        """Constructor"""
        super(CtaGGStrategy, self).__init__(ctaEngine, setting)
        # 创建K线合成器对象
        self.bm = BarManager(self.onBar)
        #self.bm = BarManager(self.onBar, 2, self.on5minBar)        # 创建K线合成器对象
        self.am = ArrayManager()

        # 注意策略类中的可变对象属性（通常是list和dict等），在策略初始化时需要重新创建，
        # 否则会出现多个策略实例之间数据共享的情况，有可能导致潜在的策略逻辑错误风险，
        # 策略类中的这些可变对象属性可以选择不写，全都放在__init__下面，写主要是为了阅读
        # 策略时方便（更多是个编程习惯的选择）

    def onInit(self):
        """初始化策略（必须由用户继承实现）"""
        #self.writeCtaLog(u'Demo演示策略初始化')

        # ROBINLIN initial the varlist
        # todo initial from the database
        if abs(self.startPrice) < 1.0e-9 and abs(self.endPrice) < 1.0e-9 and abs(self.profit) < 1.0e-9 and not self.priceGrid:
            #self.writeCtaLog(u'parameter need initialization')
            self.startPrice = 450.0
            self.endPrice = 550.0
            self.priceGrid = [int(453.00 + i* 10.0)  for i in range(0,10)]
            self.profit = 15.00
            self.lastClose = 0.0
            self.posGrid = {"{}".format(int(i)): 0 for i in self.priceGrid}  #todo: right place here?
        else:
            self.writeCtaLog(u'parameter initialized from database')

        self.bNewDay = True #set Flag for a new day
        #self.orderList = []
        #self.orderList = self.ctaEngine.orderStrategyDict[]
        self.putEvent()

    #----------------------------------------------------------------------
    def onStart(self):
        """启动策略（必须由用户继承实现）"""
        #self.writeCtaLog(u'Demo演示策略启动')
        self.putEvent()

    #----------------------------------------------------------------------
    def onStop(self):
        """停止策略（必须由用户继承实现）"""
        self.writeCtaLog(u'Demo演示策略停止')
        # 同步数据到数据库
        self.saveSyncData()
        self.writeCtaLog("onStop:同步数据到数据库")
        self.putEvent()

    #----------------------------------------------------------------------
    def onTick(self, tick):
        """收到行情TICK推送（必须由用户继承实现）"""
        #self.writeCtaLog(u'Demo Get a TICK')
        self.bm.updateTick(tick)

        # if not self.inited or not self.trading:  # strategy not inited or not started
        #     self.writeCtaLog("onTick::策略未初始化或未启动，不处理TICK信息")
        #     return
        #
        # try:
        #     ticktime = tick.datetime.time() #datetime.strptime(tick.datetime,"%H:%M:%S")
        #     tickdate = tick.datetime.date()
        # except ValueError:
        #     self.writeCtaLog("onTick::TICK中的时间错误{}".format(tick.time))
        #     # 2018-01-14 07:49:38,319  INFO: CTA_STRATEGY	管刚策略:onTick::TICK中的时间错误09:23:42.0
        #     return
        #
        # weekno = tickdate.weekday()   #wrong!need to check the tick date
        # if self.bNewDay and weekno < 5 and ticktime > time(9,0):   # 确保工作日执行一次
        #     self.writeCtaLog("onTick::工作日{} 开盘{}".format(tickdate,ticktime))
        #     # 撤销之前发出的尚未成交的委托（包括限价单和停止单）
        #     self.cancelAll()
        #     sleep(10)
        #     self.tick_rebalance(tick) # todo, 以什么价格进去买？
        #     self.bNewDay = False
        #     # 同步数据到数据库
        #     self.saveSyncData()
        #     self.writeCtaLog("onTick::同步数据到数据库")
        #     self.putEvent()

    def tick_rebalance(self,tick):
        """根据最新价格调整仓位"""
        for grid in self.priceGrid:
            if grid < tick.askPrice1 and self.posGrid["{}".format(int(grid))] == 0:
                self.buy(grid, 1)
                self.writeCtaLog("rebalance::buy@price:{}".format(grid))

        for grid in self.posGrid.keys():
            position = self.posGrid[grid]
            sellPrice = float(grid) + self.profit * 100 * position
            if position > 0: # has position
                self.sell(sellPrice,position)
                self.writeCtaLog("rebalance::sell position{}@price:{}".format(grid,sellPrice/100))

    def bar_rebalance(self,bar):
        """根据最新价格调整仓位"""
        for grid in self.priceGrid:
            if grid < bar.close and self.posGrid["{}".format(int(grid))] == 0:
                vtOrderIDList = self.buy(grid, 1)
                self.writeCtaLog("bar_rebalance::buy@price:{}".format(grid))
                self.writeCtaLog("bar_rebalance::vtOrderIDList:{}".format(vtOrderIDList))

        for grid in self.posGrid.keys():
            position = self.posGrid[grid]
            sellPrice = float(grid) + self.profit * 100 * position
            if position > 0: # has position
                self.sell(sellPrice,position)
                self.writeCtaLog("bar_rebalance::sell position{}@price:{}".format(grid,sellPrice/100))
    #----------------------------------------------------------------------
    def onBar(self, bar):
        """收到Bar推送（必须由用户继承实现）"""
        self.writeCtaLog('onBar')
        #self.bm.updateBar(bar)

        am = self.am
        am.updateBar(bar)

        if not self.inited or not self.trading:  # strategy not inited or not started
            self.writeCtaLog("onBar::策略未初始化或未启动，不处理BAR信息")
            return

        try:
            bartime = bar.datetime.time() #datetime.strptime(tick.datetime,"%H:%M:%S")
            bardate = bar.datetime.date()
        except ValueError:
            self.writeCtaLog("onBar::BAR中的时间错误{}".format(bar.time))
            # 2018-01-14 07:49:38,319  INFO: CTA_STRATEGY	管刚策略:onTick::TICK中的时间错误09:23:42.0
            return

        weekno = bardate.weekday()   #wrong!need to check the tick date
        if self.bNewDay and weekno < 5 and bartime > time(9,0):   # 确保工作日执行一次
            self.writeCtaLog("onBar::工作日{} 开盘{}".format(bardate,bartime))
            # 撤销之前发出的尚未成交的委托（包括限价单和停止单）
            self.cancelAll()
            sleep(10)
            self.bar_rebalance(bar) # todo, 以什么价格进去买？
            self.bNewDay = False
            # 同步数据到数据库
            self.saveSyncData()
            self.writeCtaLog("onBar::同步数据到数据库")
            self.putEvent()

    # ----------------------------------------------------------------------
    def on5minBar(self, bar):
        """收到X分钟K线"""
        self.writeCtaLog('on5minBar')
        # 全撤之前发出的委托
        #self.cancelAll()

        # 保存K线数据
        am = self.am
        am.updateBar(bar)

        if not am.inited:
            return

        # 同步数据到数据库
        #self.saveSyncData()

        # 发出状态更新事件
        self.putEvent()

    def onOrder(self, order):
        """收到委托变化推送（必须由用户继承实现）"""
        #super(CtaGGStrategy, self).onOrder(order)
        self.writeCtaLog( "onOrder::{}".format(order.__dict__))  # status 未成交/拒单
        # 移除重复ORDER
        for item in self.orderList:
            if item['vtOrderID'] == order.vtOrderID:
                self.orderList.remove(item)
        # 加入有效委托
        if order.status in self.STATUS_UNFINISHED:
            self.orderList.append(order.__dict__)

        # json_string = json.dumps([ob.__dict__ for ob in self.orderList])
        # self.writeCtaLog("onOrder::收到委托变化推送{}".format(json_string))
        # 同步数据到数据库
        self.saveSyncData()
        self.writeCtaLog("onOrder::同步数据到数据库")
        self.putEvent()

    def onAccountEvent(self,  account):  #event,
        pass
        """收到账号信息推送"""
        #self.writeCtaLog("onAccountEvent::account:" + str(account))
        # print "onAccountEvent::account:" + str(account.__dict__)

    def onPositionEvent(self, position):  #event,
        # """收到仓位信息推送"""
        # self.writeCtaLog("onPositionEvent::position:{}".format(position))
        self.pos = position.position
        if position.vtSymbol == self.vtSymbol:
             print "onPositionEvent::position:" + str(position.position)
             posFromGrid = 0
             for grid in self.posGrid.keys():
                 posFromGrid += self.posGrid[grid]

             if int(posFromGrid)!=int(position.position):
                self.onStop()
                print "onPositionEvent::仓位不匹配，停止策略:{}！={}".format(position.position,posFromGrid)

    #----------------------------------------------------------------------
    def onTrade(self, trade):
        self.writeCtaLog( "onTrade::处理成交确认")

        # -----------------------------------------------------------------------------------
        # 如成交价格远离网格区域，退出
        if trade.price < self.priceGrid[0]-5 or trade.price > self.priceGrid[-1]+5:
            self.writeCtaLog("onTrade::成交价格异常，停止策略:{}".format(trade.price))
            self.onStop()
            return

        # -----------------------------------------------------------------------------------
        # 寻找最靠近成交价的网格
        rightIndex = bisect.bisect(self.priceGrid, trade.price)
        if rightIndex == 0:
            positionIndex = 0
        elif rightIndex == len(self.priceGrid):
            positionIndex = len(self.priceGrid)-1
        else:
            leftIndex = rightIndex - 1
            positionIndex = rightIndex if abs(trade.price - self.priceGrid[rightIndex]) < abs(trade.price - self.priceGrid[leftIndex]) else leftIndex

        selectedGrid = self.priceGrid[positionIndex]
        self.writeCtaLog("onTrade::最靠近成交价{}的网格是:{}".format(trade.price,selectedGrid))

        # -----------------------------------------------------------------------------------
        # 更新网格仓位字典
        if trade.direction == DIRECTION_LONG:# CTAORDER_BUY :
            self.posGrid[str(selectedGrid)] = self.posGrid[str(selectedGrid)]+trade.volume
            self.writeCtaLog("onTrade::网格{}处仓位增加{} 变成{}".format(selectedGrid,trade.volume,self.posGrid[str(selectedGrid)]))
        elif trade.direction == DIRECTION_SHORT:#CTAORDER_SELL:
            self.posGrid[str(selectedGrid)] = self.posGrid[str(selectedGrid)] - trade.volume
            self.writeCtaLog("onTrade::网格{}处仓位减少{} 变成{}".format(selectedGrid,trade.volume,self.posGrid[str(selectedGrid)]))

        # -----------------------------------------------------------------------------------
        # 同步数据到数据库   ？这步多余？ processTradeEvent in ctaEngine.py has the same operation
        self.saveSyncData()
        self.writeCtaLog("onBar::同步数据到数据库")

        # -----------------------------------------------------------------------------------
        #交易信息写入CSV
        # TradeInfo 所在路径
        vnTrader_dir = 'd:\\vnpy\\trader\\app\\ctaStrategy\\TradeInfo'
        today = datetime.datetime.now().strftime("%Y-%m-%d")

        # 文件名称设置为今天名称, 每次只推送一条合约信息
        path = vnTrader_dir + '\\TradeInfo_' + today + '.csv'
        if not os.path.exists(path): # 如果文件不存在，需要写header
            with open(path, 'w',newline="") as f:#newline=""不自动换行
                w = csv.DictWriter(f, list(trade.__dict__.keys()))
                w.writeheader()
                w.writerow(trade.__dict__)
        else: # 文件存在，不需要写header
            with open(path, 'a',newline="") as f:  #a追加形式写入
                 w = csv.DictWriter(f, list(trade.__dict__.keys()))
                 w.writerow(trade.__dict__)
                 #sleep(60)  #每隔一分钟查询一次
                 #return    #如果文件存在不写入

        # 发出状态更新事件
        self.putEvent()

    #----------------------------------------------------------------------
    def onStopOrder(self, so):
        """停止单推送"""
        pass

    # def createPosIndexArray(self, grid=[], pos=[]):
    #     gridIndex = [0] * len(grid)
    #     for price in pos:
    #         if price < grid[-1] + 10 and price > grid[0] - 10:  # 订单价在，网格+-10的范围内
    #             rightIndex = bisect.bisect(grid, price)
    #             if rightIndex == 0: # 低于最低网格
    #                 gridIndex[0] = 1
    #             elif rightIndex == len(grid): # 高于最高网格
    #                 gridIndex[-1] = 1
    #             else:
    #                 leftIndex = rightIndex - 1
    #                 positionIndex = rightIndex if abs(price - grid[rightIndex]) < abs(
    #                     price - grid[leftIndex]) else leftIndex
    #                 gridIndex[positionIndex] = 1
    #
    #     return gridIndex

    def cancelAll(self):
         #json_string = json.dumps([ob.__dict__ for ob in self.orderList])
         self.writeCtaLog("cancelAll::取消所有委托{}".format(self.orderList))
         for order in self.orderList:
             self.writeCtaLog("cancelAll::取消委托{}".format(order['vtOrderID']))
             if STOPORDERPREFIX in order['vtOrderID']:
                  self.ctaEngine.cancelStopOrder(order['vtOrderID'])
             else:
                self.ctaEngine.cancelOrder(order['vtOrderID'])

         #self.orderList = []
         # 同步数据到数据库
         #self.saveSyncData()
         #self.writeCtaLog("cancelAll::同步数据到数据库")
         self.putEvent()