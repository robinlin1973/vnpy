# encoding: UTF-8

# 重载sys模块，设置默认字符串编码方式为utf8
import sys
import multiprocessing
from time import sleep
from datetime import datetime, time

reload(sys)
sys.setdefaultencoding('utf8')

# vn.trader模块
from vnpy.event import EventEngine
from vnpy.trader.uiQt import createQApp
from vnpy.trader.uiMainWindow import MainWindow
from vnpy.trader.vtEngine import MainEngine, LogEngine

# 加载底层接口
from vnpy.trader.gateway import (ctpGateway, oandaGateway, ibGateway,
                                 tkproGateway)
from vnpy.trader.gateway import (femasGateway, xspeedGateway,
                                     futuGateway, secGateway)

# 加载上层应用
from vnpy.trader.app import (riskManager, ctaStrategy)
from vnpy.trader.vtGlobal import globalSetting

import itchat

# ----------------------------------------------------------------------
def runChildProcess():
    """主程序入口"""
    # 创建Qt应用对象
    qApp = createQApp()

    # 创建事件引擎
    ee = EventEngine()

    # 创建主引擎
    me = MainEngine(ee)

    # 添加交易接口
    me.addGateway(ctpGateway)
    me.addGateway(tkproGateway)
    me.addGateway(oandaGateway)
    me.addGateway(ibGateway)

    me.addGateway(femasGateway)
    me.addGateway(xspeedGateway)
    me.addGateway(secGateway)
    me.addGateway(futuGateway)

    # 添加上层应用
    me.addApp(riskManager)
    me.addApp(ctaStrategy)

    # 自动连接
    if globalSetting['start_Gateway']!=None:
        me.connect(globalSetting['start_Gateway'])  # ROBIN LIN

    # 创建主窗口
    mw = MainWindow(me, ee)
    mw.showMaximized()

    # 自动显示CTA策略窗口
    for appDetail in mw.appDetailList:
        if appDetail['appName'] == globalSetting['start_App']:#'CtaStrategy':
            appName = appDetail['appName']
            try:
                mw.widgetDict[appName].show()
            except KeyError:
                appEngine = mw.mainEngine.getApp(appName)
                mw.widgetDict[appName] = appDetail['appWidget'](appEngine, mw.eventEngine)
                mw.widgetDict[appName].show()

    # Back up the reference to the exceptionhook
    sys._excepthook = sys.excepthook

    # 在主线程中启动Qt事件循环
    try:
        sys.exit(qApp.exec_())
    except:
        print("Exiting")

def my_exception_hook(exctype, value, traceback):
    # Print the error and traceback
    print(exctype, value, traceback)
    # Call the normal Exception hook after
    sys._excepthook(exctype, value, traceback)
    sys.exit(1)


#----------------------------------------------------------------------
def runParentProcess():
    """父进程运行函数"""
    # 创建日志引擎
    le = LogEngine()
    le.setLogLevel(le.LEVEL_INFO)
    le.addConsoleHandler()
    le.addFileHandler()

    le.info(u'启动CTA策略守护父进程')

    #DAY_START = time(8, 55)         # 日盘启动和停止时间
    DAY_START = time(8, 55)         # 日盘启动和停止时间
    DAY_END = time(15, 05)
    #DAY_END = time(8, 14)

    NIGHT_START = time(20, 55)      # 夜盘启动和停止时间
    #NIGHT_START = time(16, 43)      # 夜盘启动和停止时间
    NIGHT_END = time(23, 35)
    #NIGHT_END = time(16, 44)

    SHUT_START = time(15, 05)
    SHUT_END = time(20, 55)

    p = None        # 子进程句柄

    while True:
        currentTime = datetime.now().time()
        weekno = datetime.today().weekday()
        #recording = False
        recording = True
        if not itchat.instanceList[0].alive:
            itchat.auto_login(hotReload=True)


        # 判断当前处于的时间段
        # if ((currentTime >= DAY_START and currentTime <= DAY_END) or
        #     (currentTime >= NIGHT_START and currentTime <= NIGHT_END)):
        #     recording = True
        if(currentTime >= SHUT_START and currentTime <= SHUT_END) or weekno >= 5: #shut at weekend as well
            recording = False


        # 记录时间则需要启动子进程
        if recording and p is None:
            le.info(u'启动子进程')
            p = multiprocessing.Process(target=runChildProcess)
            p.start()
            le.info(u'子进程启动成功')


        # 非记录时间则退出子进程
        if not recording and p is not None:
            le.info(u'关闭子进程')
            p.terminate()
            p.join()
            p = None
            le.info(u'子进程关闭成功')

        sleep(5)


if __name__ == '__main__':
    #runChildProcess()

    # 尽管同样实现了无人值守，但强烈建议每天启动时人工检查，为自己的PNL负责
    runParentProcess()