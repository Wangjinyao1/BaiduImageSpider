#!/usr/bin/env python
# -*- coding:utf-8 -*-

# ================= 导入必要的Python标准库部分 =================
import argparse    # 用于解析命令行参数，让脚本可以通过终端传入参数运行
import os          # 操作系统接口模块，用于创建文件夹、判断文件是否存在等
import re          # 正则表达式模块，用于从字符串中匹配特定的模板（例如提取文件后缀）
import sys         # 系统特定的参数和功能，主要用于读取 sys.argv 看是否有终端输入参数
import urllib      # 提供了基本的URL处理功能
import json        # 用于解析和生成JSON数据格式（百度返回的数据就是JSON数据）
import socket      # 提供底层网络接口，在这里主要用于捕获网络连接超时的错误
import urllib.request # 专门用于打开和读取网页的库
import urllib.parse   # 专门用于解析、拼接、转码URL的库
import urllib.error   # 包含由 urllib.request 抛出的异常
import time        # 时间模块，主要用于控制爬虫的速度（sleep暂停），防止请求太快被封

# 设置全局的网络请求超时时间，如果5秒钟连不上服务器，则会自动抛出 timeout 异常
timeout = 5
socket.setdefaulttimeout(timeout)


class Crawler:
    """
    百度图片搜索引擎爬虫核心类。
    包含了抓取网页连接、翻页读取、保存图片资源到本地硬盘等功能。
    """
    # ====== 类的私有属性定义 (双下划线代表内部调用) ======
    __time_sleep = 0.1   # 请求之间的基础睡眠时间(秒)，防止请求过快被识别为机器爬虫从而封停IP
    __amount = 0         # 总共需要抓取的图片数量上限目标
    __start_amount = 0   # 抓取的起始偏移点（即你需要跳过前面的多少张图片开始抓起）
    __counter = 0        # 全局计数器，记录当前成功下载到本地的图片数量
    
    # HTTP 请求头(Headers)的伪装。目的是骗过服务器，让对方以为我们是用正常的火狐浏览器(Firefox)在访问，而不是自动脚本程序。
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:23.0) Gecko/20100101 Firefox/23.0', 
        'Cookie': '' # 用于存放和维护访问过程中产生的Cookie会话信息
    }
    __per_page = 30 # 百度图片动态加载的瀑布流接口中，每次最多返回30张图片的数据流

    # 类的初始化函数（构造函数）
    # 当在外部使用 Crawler(0.05) 创建出一个爬虫对象时，会自动首先执行这里
    def __init__(self, t=0.1):
        """
        :param t: 每张图片下载之间的睡眠时间间隔（秒）。向外界暴露这个变量用于精细调整抓取速度
        """
        self.time_sleep = t

    # 静态方法装饰器（表明这个方法不需要实例化就能单独调用，因为它内部没有用到类似 self.xxx 的对象属性）
    @staticmethod
    def get_suffix(name):
        """
        通过正则表达式机制获取下载图片链接的后缀名（比如 .jpg、.png、.bmp 等）
        :param name: 获取到的原生图片网址URL
        :return: 对应的图片后缀字符串格式
        """
        # 正则表达式细节： \.匹配真正的点号； [^\.]*匹配后面没有任何点号的任意字符串； $定位必须是以这串字符串为结尾。
        m = re.search(r'\.[^\.]*$', name)
        # 如果解析出了有效内容，并且找到的带点的后缀长度合理（<=5 比如 .jpeg 长度为5），就确认返回它
        if m and m.group(0) and len(m.group(0)) <= 5:
            return m.group(0)
        else:
            # 如果解析失败或者没有扩展名，通常默认当作最常见的 jpeg 照片格式即可
            return '.jpeg'  

    @staticmethod
    def handle_baidu_cookie(original_cookie, cookies):
        """
        处理、提取和智能合并百度的Cookie，帮助更好地躲避反爬虫机制。
        :param original_cookie: 原本我们现有的 Cookie 字符串
        :param cookies: 这次网页发送网络请求后新下发的 Cookie 列表组合
        :return: 拼接出最新鲜完整的 Cookie 字符串
        """
        if not cookies: # 如果这次新请求没有下发cookie，继续直接沿用老的
            return original_cookie
            
        result = original_cookie
        for cookie in cookies:
            # 取出每条Cookie里真正有用的第一部分并用分号分段连接起来
            result += cookie.split(';')[0] + ';'
        result.rstrip(';') # 去除最末尾多余无用的分号
        return result

    def save_image(self, rsp_data, word):
        """
        处理和提取网络接口传来的数据，并真正负责将获取到的图片实物逐个下载写入到本地硬盘。
        :param rsp_data: 百度接口返回回来的标准经过解析的JSON格式的数据字典，里面包含当前这一页的图片链接
        :param word: 用户搜索验证的关键词（在这里自动利用其为名字创建归档文件夹）
        """
        # 1. 检查当前程序目录下是否已经存在了同名的内容文件夹，如果没有则立即自动创建
        if not os.path.exists("./" + word):
            os.mkdir("./" + word)
            
        # 2. 判断该归类文件夹里原先有几张图片了，获取其基准长度，防止断点重连续传的时候旧照片名字被重叠覆盖
        self.__counter = len(os.listdir('./' + word)) + 1
        
        # 3. 遍历接口返回给我们包含所有相关图片信息的列表
        for image_info in rsp_data['data']:
            try: # 以下每张图片的下载都是有可能会报错的流程，放进 try 里进行保护
            
                # 预先筛查，确保拿到的数据里真的有存放我们实打实需要的原始图片直连地址池（replaceUrl）
                if 'replaceUrl' not in image_info or len(image_info['replaceUrl']) < 1:
                    continue # 什么都没包含这往往是个脏数据直接跳过
                
                # 成功从层层字典里提取原图的高清下载链接 obj_url 和小图(缩略图)的链接 thumb_url
                obj_url = image_info['replaceUrl'][0]['ObjUrl']
                thumb_url = image_info['thumbURL']
                
                # 采用百度提供的带有缓存机制的中转下载接口地址去间接接管下载过程。
                # 注意里面 urllib.parse.quote 的作用是将原本链接里包含的特殊非法或非英文字符强制变成合乎规定的安全 URL 传参（也就是百分号编码）。
                url = 'https://image.baidu.com/search/down?tn=download&ipn=dwnl&word=download&ie=utf8&fr=result&url=%s&thumburl=%s' % (urllib.parse.quote(obj_url), urllib.parse.quote(thumb_url))
                
                # 真实请求目标之前让程序休眠片刻(前面传进来的间隔设定)，对服务器保持一定温柔友好也可以降低封禁风险
                time.sleep(self.time_sleep)
                suffix = self.get_suffix(obj_url) # 调用上面的方法，精准预判图片的拓宽名形式
                
                # 开始构造下载专用的 urllib 开场管理对象 (opener)，继续深度伪装成合规浏览器！
                opener = urllib.request.build_opener()
                opener.addheaders = [
                    ('User-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.116 Safari/537.36'),
                    ('Referer', 'https://image.baidu.com/'), # 添加 Referer 信息，告诉服务器“这个图片请求我是直接从你们官网跳进来的”，以此骗取信任防止出现防盗链。
                ]
                urllib.request.install_opener(opener) # 使这个新特性全局生效，确保马上启用的 urlretrieve 下载也是以这个身份进行的
                
                # 敲定这幅图片的相对落地存储地址。形如： ./美少女/1.jpeg
                filepath = './%s/%s' % (word, str(self.__counter) + str(suffix))
                
                # -----------------这里是该项目的灵魂，全自动发起下载的核心动作-----------------
                urllib.request.urlretrieve(url, filepath)
                
                # 验证下载下来这个新出炉的文件是否健康（若是遭受防盗链或者假数据，接口经常丢出一个空文件（比如只有0-2个字节））
                if os.path.getsize(filepath) < 5:
                    print("下载到了空文件，跳过!")
                    # 删除因为失效被制造的空垃圾占位符，保持盘间清爽
                    os.unlink(filepath)
                    continue # 放弃当前，直接回到首段继续进入下一次图片的探索循环
                    
            # 内部单图异常处理机制一：捕获下载过程中可能出现的各种已知 HTTP 网络连接方面的错误（比如链接失效报了404）
            except urllib.error.HTTPError as urllib_err:
                print(urllib_err)
                continue
            # 内部单图异常处理机制二：以防万一直接囊括拦截所有上面没列出发生的意外，避免千里之堤溃于一蚁
            except Exception as err:
                time.sleep(1) # 有异常出错不一定急，强行喘息1秒钟，避免引起更剧烈的接口连锁反应
                print(err)
                print("产生未知错误，放弃保存")
                continue
            else:
                # 只有当此张图片一切的所有 try 操作行云流水地完成而没有任何一个异常被触发，才会最终进入这个 else 区。意味着一切下载完美成功！
                print("保存图片成功 +1, 库房里已有 " + str(self.__counter) + " 张图")
                self.__counter += 1
        return

    def get_images(self, word):
        """
        向外网发出请求索要核心数据的引擎，他是驱动一切下载流水线顺利翻页前进的大滚轴。
        :param word: 提交去发给百度的最终搜索词汇
        """
        # 将我们习惯的中文字符（如“美少女”）用百分号方法翻译转换成网络引擎认识的形态结构。如"%E7%BE%8E..."
        search = urllib.parse.quote(word)
        
        # pn (全称 page number): 记录当程序下一次向接口发起请求请求时，该从哪个图集偏移量开始往下拿。
        pn = self.__start_amount
        
        # 总开关监控闸门：只要当前推进获取的图片偏移量下标由于翻页还不足我们给定的上限(amount)，就在循环里永远不停搜下去
        while pn < self.__amount:
            # 配置百度的图片图片动态分页API加载地址(这通常叫Ajax/JSON交互)，动态将拼凑出的查询搜索词串（search）、偏移距离位置（pn）、每页想带走多少图片总量（rn）缝合带入其里面。
            url = 'https://image.baidu.com/search/acjson?tn=resultjson_com&ipn=rj&ct=201326592&is=&fp=result&queryWord=%s&cl=2&lm=-1&ie=utf-8&oe=utf-8&adpicid=&st=-1&z=&ic=&hd=&latest=&copyright=&word=%s&s=&se=&tab=&width=&height=&face=0&istype=2&qc=&nc=1&fr=&expermode=&force=&pn=%s&rn=%d&gsm=1e&1594447993172=' % (search, search, str(pn), self.__per_page)
            
            try:
                # 模拟正常人浏览网页的操作：每次点下一页之前稍微在第一页停留一会（由前调配置）
                time.sleep(self.time_sleep)
                # 构建装配带好伪装属性头部 headers 的高级复杂请求包裹，而非廉价的直接访问包裹（那通常一发就拒）
                req = urllib.request.Request(url=url, headers=self.headers)
                # 端装发往服务器接收第一手最原始网页信息的页面返回
                page = urllib.request.urlopen(req)
                # 强行抢走并继承此回服务器刚颁布给我们的临时Cookie身份印记并放入下次的header配置中，这样对方就会一直错误坚信“这是一个连续浏览了好半天的普通正常老实顾客”
                self.headers['Cookie'] = self.handle_baidu_cookie(self.headers['Cookie'], page.info().get_all('Set-Cookie'))
                # 读取这个包裹页面所传达给你的一切最核心真实二进制形式字节流资讯（此时还没破解成能读懂的文字）
                rsp = page.read()
                page.close() # 拿完即焚关闭挂载链接回收服务器信道
                
            # 三段容灾拦截准备：
            # 捕获万一由于返回包混入杂包导致的文字格式强行转换崩溃问题
            except UnicodeDecodeError as e:
                print(e)
                print('-----出现未知文字编码致命错误 UnicodeDecodeError:', url)
            # 无意中如果传入了不规则网址产生的库自崩提醒
            except urllib.error.URLError as e:
                print(e)
                print("-----该URL在构成上发生严重失败 urlError:", url)
            # 如果等了上述设定好的 5S timeout 还是没响应则爆出超时错避免永远等下去
            except socket.timeout as e:
                print(e)
                print("-----网络连接等不到反应已断线超时 socket timout:", url)
                
            else: # -----------请求顺利通讯没有任何差错的时候执行！--------------
                try:
                    # 将拿回来的加密二进制数据强行往能够读懂的 utf-8 字符串字典上转，“ignore”用来忽略个别生僻出格的没法识别的怪异小语种等文字。
                    rsp_str = rsp.decode('utf-8', errors='ignore')
                    # 清理从百度拿回来的不规矩数据。百度经常随性乱用 JavaScript 的单引号直接转义为(\')作为字符串符号，但在这会触发标准 Python 解析模块的抗议死因！全局搜刮清理掉它。
                    rsp_str = re.sub(r"\\'", "'", rsp_str)
                    
                    # 使用强大的 JSON 提取器将修补过后的长段文本字符精确地变为 Python 世界内部方便取用遍历的“高级字典”骨架结构！
                    rsp_data = json.loads(rsp_str, strict=False)
                    
                except json.decoder.JSONDecodeError as e:
                    # 如果这页数据已经烂泥扶不上墙怎么抢救也无法被按照 JSON 解析，不阻碍主循环而是大方报告然后跨步放掉本页数据。
                    print("JSON解析出现严重失败，本页接口给出的数据内可能存在非法污染字符：", e)
                    print("已启动自动放弃：跳过此页，程序继续向前爬下一页的数据...")
                    pn += self.__per_page
                    continue # 触发跨步继续前进进入下一个 pn 取值循环

                # 字典构建好了以后，第一件事情判定如果里面居然没有被叫做 'data' 这个装满我们所需关键图库信息的总钥匙扣
                if 'data' not in rsp_data:
                    # 往往最大的原因是因为此时访问速度过快了被百度的反抓取拦截防御系统的验证码页面拦住了视线强行重定向转了发走导致了空壳。
                    print("注意:疑似访问异常短时间触发了反爬拦截防御机制返回错乱，不推进循环强制停位自动准备重试刷新本页...")
                else:
                    # 天助我也拿到了含 data 密码的终极宝库数据字典！顺手交给我们刚刚写好的存图引擎去一张一张地卸载货吧！
                    self.save_image(rsp_data, word)
                    # 货物全卸载完了以后！报告提示翻页动作！
                    print("本页内容已基本尽入囊中，拉取下一页补充战果...")
                    # 控制翻页大滚轴偏移量增加 __per_page（相当于往后加了30页数字跨度），使得进入下一回while验证，拿到不同新页地址
                    pn += self.__per_page
                    
        # 整套无限外围滚轴 while 流程安全退出，到达设定的目标 amount 数值大关结束！
        print("所有下载页签任务核算完成，已功成身退完全退出引擎")
        return

    def start(self, word, total_page=1, start_page=1, per_page=30):
        """
        爬虫入口统一规划枢纽站。作为外部向内传接命令第一首当冲锋的地方，主要用于计算到底总共抓多少？什么时候出发和什么时候退网关机。
        :param word: 用户提交的需求抓取的关键词搜索目标
        :param total_page: 需要抓取数据的目标页数 （也就是总共最后会有：设定页数 x 每页数量的庞大相册返回）
        :param start_page: 声明从第几页的地方起手开抓（例如设为 2，系统判定相当于你抛弃跳过了前30张烂大街同质化图片直冲后续结果起步下载）
        :param per_page: 告诉系统每次往爬取小推车翻页加载的数量级是多少（默认设定30，这是因为百度页面每次滚轮下拉默认就是补充30张图片左右的最佳经验设定值）
        """
        self.__per_page = per_page
        
        # 起步落子运算：比如我们要求从第 2 页起抓起，每页上限容量是30张图，那么内部起点偏移量就是 (2-1)*30 = 30（从而完美越过原本属于首推页展示序列占位的 0-30号区间）
        self.__start_amount = (start_page - 1) * self.__per_page
        
        # 退出阀门预置：如果你的最终预想共想抓足足 2 页，且每页 30图，当前起手偏移基准是从 30 开始跑点的，那么只要到达了（2*30）+30 = 90的地方，这趟活就必须终止结算了！
        self.__amount = total_page * self.__per_page + self.__start_amount
        
        # 核心三大定位全局目标准备落定，直接开马达调用 get_images 主引擎起跑！
        self.get_images(word)


# 这是标准 Python 识别模块独立入口判断语法：如果是以纯粹执行这个名为 *.py 的脚本作为程序起点启动引擎的，那么就会有幸走到 if 下面开展后面的任务进程。如果只是被别处用 import 代码当库导入的组件，绝不会触发这些独立测试代码段的运行搞破坏！
if __name__ == '__main__':

    # 判断我们在黑框终端命令行激活命令的时是否手动画蛇添足加了额外的输入属性传参（长度必然大于代表自己文件名本身占位的参数位置长度 1）
    if len(sys.argv) > 1:
        # 如果是极客用户，直接初始化大名鼎鼎的命令行高级解析接管库 argparse 用于处理极其繁杂优雅的传参调参匹配与容错管理
        parser = argparse.ArgumentParser()
        # 增加一连串自定义入参字段名。 required=True 代表这是每次硬需必须给出的重要指示目标，不然直接报错拒绝执行！
        parser.add_argument("-w", "--word", type=str, help="抓取关键词", required=True)
        parser.add_argument("-tp", "--total_page", type=int, help="需要抓取的总页数", required=True)
        parser.add_argument("-sp", "--start_page", type=int, help="起始页数", required=True)
        # 用 choice 设置了一个小关卡只有输入落在 10-100之间的整数才允许它通过传进来！而且提供了哪怕你漏了参数时也不畏惧的有底气预设缺省保底传参 default 值！
        parser.add_argument("-pp", "--per_page", type=int, help="每页大小", choices=[10, 20, 30, 40, 50, 60, 70, 80, 90, 100], default=30, nargs='?')
        parser.add_argument("-d", "--delay", type=float, help="抓取延时（间隔）", default=0.05)
        # 全部字段配置宣发完成打包执行正式获取并拆解转换成好用的结构字典映射变量集合放入 args 里统一归集接管
        args = parser.parse_args()

        crawler = Crawler(args.delay)
        # 利用终端敲进去配置下来的变量内容，毫无隐瞒毫无卡壳的开足马力进行 start 起跑动作。
        crawler.start(args.word, args.total_page, args.start_page, args.per_page)  
        
    else:
        # 【对新手最友好的部分】如果我们只是单纯的一个从不敲小黑框的小萌新，在任何界面工具 (比如 PyCharm 或是网页上的 Jupyter 等编辑器) 里面仅仅由于冲动直接按下了左肩那个诱人的绿色【倒三角Run】按钮！且没带有任何的包袱后缀指令.....
        
        # 好的！别担心程序抛锚，我们在这里预留一个专供于傻瓜纯绿色点启用的全套傻瓜安全保底路线配置！去安然静默运作下面所有的预定指令！！
        
        # 实例化一只名叫 crawler 的崭新鲜活实体图片下载爬虫工人，并明确教导它：不准跑太快累死要每次摸鱼打盹个 0.05 秒。
        crawler = Crawler(0.05)  

        # 使用完全用代码铁写定死的硬编码指令让这位工人开饭起程！！
        # 这句指令的大白话翻译就是：
        # 请给我想办法下关键词归档名为“美少女”系列的任何图片。
        # 我只要足足实打实的 2 整个页面的货！（对应了 total_page 的第2部分选项）
        # 请从第 1 页最打头部分给我算起搜罗（对应了 start_page 第3个选项）！
        # 每一页里面我期待你们拿满一箩筐能装刚好 30 张的东西！（对应给的最后 per_page 单页额度设定！）
        # （最终期待你的战果将是带回：2*30=共计60张美丽的大海报！！！）
        crawler.start('美少女', 2, 1, 30)  
        
        # 想要多开？或者换换口味口味不同风格的，我帮你想好放在这儿预留当了备用小提示库选项。直接删除前头的 '#' 注释就能把他们也唤醒一起抓更多。
        # crawler.start('二次元 美女', 10, 1)  # （比如抓取关键词为 “二次元 美女”的数据）
        # crawler.start('帅哥', 5)  # （抓取关键词为 “帅哥”的小哥数据集）
