"""生成电商演示数据并完成入库。

用法（在项目根目录、已配置 DASHSCOPE_API_KEY 的情况下）：
    .\\.venv\\Scripts\\python.exe scripts\\seed_demo.py

脚本是幂等的：知识库、文档、演示用户已存在时会自动跳过。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal, close_db, init_db  # noqa: E402
from app.models import Document, IngestionTask, KnowledgeBase, User, new_id  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services.ingest import ingest_document  # noqa: E402

KB_SPECS = [
    {
        "name": "数码家电知识库",
        "description": "手机、笔记本、耳机等数码产品的参数、售后与配送说明",
        "docs": {
            "星耀 X50 5G 手机商品详情.md": """# 星耀 X50 5G 手机

## 基本信息
- 商品编号：SX-X50-256
- 品牌：星耀
- 上市时间：2025 年 9 月
- 颜色：曜石黑、冰川银、晨曦金
- 存储版本：12GB+256GB、12GB+512GB、16GB+1TB

## 核心参数
- 屏幕：6.78 英寸 1.5K OLED 曲面屏，120Hz 自适应刷新率，峰值亮度 3000 尼特
- 处理器：第三代骁龙 8 移动平台，台积电 4nm 工艺
- 影像：5000 万像素主摄（OIS 光学防抖）+ 5000 万像素潜望长焦（3.5 倍光学变焦）+ 5000 万像素超广角，前置 3200 万像素
- 电池：5400mAh，支持 100W 有线快充与 50W 无线快充
- 系统：星耀 OS 5.0，基于 Android 15
- 其他：IP68 防尘防水、NFC、红外遥控、双扬声器、X 轴线性马达

## 价格与促销
- 12GB+256GB：3999 元
- 12GB+512GB：4299 元
- 16GB+1TB：4999 元
- 以旧换新最高补贴 600 元；学生认证额外优惠 100 元
- 下单赠送 100W 充电套装与透明保护壳

## 包装清单
手机主机 ×1、100W 充电器 ×1、USB-C 数据线 ×1、透明保护壳 ×1、取卡针 ×1、快速入门指南 ×1、保修卡 ×1。

## 常见问题
- 是否支持双卡双待？支持 Nano-SIM + Nano-SIM 双卡，支持 5G 双卡双通。
- 是否支持卫星通信？X50 标准版不支持，X50 Pro 卫星版支持双向北斗卫星消息。
- 是否支持扩展存储？不支持 microSD 扩展，建议按需选择 512GB 或 1TB 版本。
""",
            "云帆 Pro 14 笔记本电脑商品详情.md": """# 云帆 Pro 14 轻薄笔记本

## 基本信息
- 商品编号：YF-PRO14-U7
- 定位：14 英寸高性能轻薄本，适合办公、编程与轻度创作
- 颜色：深空灰、月光银

## 配置与价格
- 处理器：英特尔酷睿 Ultra 7 155H，16 核 22 线程
- 显卡：Intel Arc 集成显卡
- 内存：32GB LPDDR5X 7467MHz（板载，不可扩展）
- 硬盘：1TB PCIe 4.0 固态硬盘，预留一个 M.2 2280 扩展位
- 屏幕：14 英寸 2.8K IPS 雾面屏，120Hz，100% sRGB，400 尼特
- 电池：75Wh，支持 100W PD 快充，标配 100W 氮化镓充电器
- 接口：2×Thunderbolt 4、1×USB-A 3.2、1×HDMI 2.1、1×3.5mm 耳机孔
- 重量：1.39kg，厚度 15.9mm
- 价格：6999 元；32GB+1TB 首发价 6499 元

## 使用说明
- 首次开机需连接电源并长按电源键 2 秒，系统会自动完成初始化。
- 支持 180 度开合，键盘三级背光，Fn+Q 切换智能/性能/安静三种模式。
- 性能模式下风扇噪音约 45 分贝，建议插电使用以释放完整性能。

## 售后
- 整机保修 2 年，主要部件保修 2 年，电池保修 1 年。
- 支持 7 天无理由退货（激活 Office 不影响）、15 天质量问题换货。
- 全国 260 个城市支持上门维修，其余地区寄修，往返运费由品牌承担。
""",
            "静界 Air 主动降噪耳机商品详情.md": """# 静界 Air 主动降噪真无线耳机

## 基本信息
- 商品编号：JJ-AIR-BLK
- 类型：入耳式真无线降噪耳机
- 颜色：墨黑、雾白、薄雾蓝
- 价格：899 元，活动价 799 元

## 核心参数
- 降噪深度：最高 48dB 自适应主动降噪，支持通透模式
- 发声单元：11mm 动圈 + 平面振膜高音单元，双单元分频
- 音频编码：SBC、AAC、LDAC，支持 Hi-Res 无线金标认证
- 蓝牙：5.4，支持双设备连接与低延迟游戏模式（最低 55ms）
- 续航：单次 7 小时，配合充电盒 32 小时；开启降噪单次 5.5 小时
- 充电：USB-C 有线 + Qi 无线充电，充电 10 分钟听歌 3 小时
- 防护：IP54 防尘防水，充电盒 IPX4
- 重量：单耳 4.6g，充电盒 42g

## 功能
- 空间音频与头部追踪，支持音乐、影院两种模式。
- 六麦克风通话降噪，抗风噪设计，地铁与街道通话清晰。
- 支持触控自定义、佩戴检测、查找耳机、固件在线升级。
- App 内提供 EQ 调节与听力测试，可生成个性化音效。

## 包装与售后
包装含耳机 ×2、充电盒 ×1、USB-C 线 ×1、耳塞套（S/M/L）×3 对、说明书 ×1。
整机保修 1 年，非人为损坏免费换新；耳塞套等耗材不在保修范围。
""",
            "数码家电售后与保修政策.md": """# 数码家电售后与保修政策

## 七天无理由退货
- 自签收之日起 7 天内，商品完好、配件齐全、不影响二次销售，可申请无理由退货。
- 手机、笔记本、耳机等 3C 数码产品需保持开机激活前的状态；已激活的手机不支持无理由退货，但可享受质量问题退换。
- 定制刻字、已拆封的耳塞套、已激活的软件服务不支持无理由退货。
- 退货运费：质量问题由商家承担；非质量问题由消费者承担，购买运费险的可由保险赔付。

## 十五天质量问题换货
- 自签收之日起 15 天内，出现非人为性能故障，经检测确认后可换新。
- 需提供订单号、故障描述与检测报告；检测由品牌授权服务中心完成。
- 同一故障更换后仍无法使用的，可申请全额退款。

## 保修政策
- 手机整机保修 1 年，主要部件（主板、屏幕、电池）保修 1 年，耳机、充电器等配件保修 6 个月。
- 笔记本整机保修 2 年，电池保修 1 年；意外损坏、进水、私自拆修不在保修范围。
- 保修期内维修免人工费与配件费；保修期外按官方报价收取费用。
- 延保服务可在下单时加购，最长可延长至 3 年。

## 售后流程
1. 在订单详情页提交售后申请，选择退货、换货或维修。
2. 客服在 24 小时内审核，审核通过后生成寄件单号。
3. 按提示寄回商品，仓库签收后 48 小时内完成检测。
4. 退款原路返回，一般 1-3 个工作日到账；换货商品 48 小时内发出。
""",
            "配送与安装服务说明.md": """# 配送与安装服务说明

## 配送范围与时效
- 全国大部分地区支持配送，港澳台及部分偏远地区暂不支持。
- 现货商品：当日 16:00 前付款，当天出库；16:00 后付款次日出库。
- 配送时效：一线城市 1-2 天，二三线城市 2-4 天，偏远地区 4-7 天。
- 大家电（冰箱、洗衣机、电视）由品牌服务商配送，配送前会电话预约时间。

## 运费规则
- 单笔订单满 99 元包邮，不满 99 元收取 8 元运费。
- 大家电默认免费送货上门，偏远地区或需上楼搬运的按实际情况收取服务费。
- 退换货运费按售后政策执行。

## 安装服务
- 空调、热水器、油烟机等需要安装的大家电，提供免费基础安装。
- 额外材料（加长铜管、支架、打孔等）按官方标准收费，师傅上门前会出示价目表。
- 安装服务可在订单页预约，支持选择工作日或周末时段。

## 签收注意事项
- 收到商品时请当面检查外包装，如有破损请拍照并拒收。
- 大家电签收后 24 小时内预约安装，超时可能影响安装排期。
- 物流信息可在订单详情页实时查看，异常件可联系在线客服处理。
""",
        },
    },
    {
        "name": "服饰鞋包知识库",
        "description": "女装、通勤包等商品的材质、尺码与退换说明",
        "docs": {
            "轻岚系列女士风衣商品详情.md": """# 轻岚系列女士中长款风衣

## 基本信息
- 商品编号：QL-FY-2025
- 品类：女士中长款风衣
- 颜色：燕麦色、雾霾蓝、经典卡其、黑色
- 尺码：XS、S、M、L、XL
- 价格：699 元，会员价 649 元

## 面料与工艺
- 面料：65% 聚酯纤维 + 32% 粘胶纤维 + 3% 氨纶，斜纹肌理，挺括不易皱。
- 里料：100% 聚酯纤维，顺滑亲肤。
- 工艺：双排扣设计，可拆卸腰带，后摆开衩，肩部有薄垫肩。
- 版型：H 型微宽松，长度约 105cm（M 码），适合通勤与日常。
- 口袋：两侧斜插袋 + 内袋一个，均带防丢拉链。

## 洗涤与保养
- 建议干洗；如手洗请使用中性洗涤剂，水温不超过 30℃。
- 不可漂白、不可烘干，阴凉处悬挂晾干。
- 熨烫温度不超过 110℃，建议垫布熨烫。
- 避免长时间暴晒与尖锐物摩擦，防止起球与勾丝。

## 穿搭建议
- 通勤：搭配衬衫与直筒西裤，腰带收腰更显比例。
- 休闲：搭配针织衫与牛仔裤，敞开穿着更随性。
- 春秋季可内搭薄款羽绒马甲，冬季建议选择加厚版本。

## 售后说明
支持 7 天无理由退换，吊牌完好、无穿着痕迹、无污渍即可。质量问题 15 天内换新。
""",
            "城市通勤双肩包商品详情.md": """# 城市通勤双肩包 26L

## 基本信息
- 商品编号：CS-BP-26
- 容量：26L
- 颜色：曜石黑、岩灰、藏青
- 价格：399 元

## 材质与结构
- 面料：900D 高密防泼水尼龙，表面 PU 涂层，小雨环境可短时防护。
- 里布：210D 涤纶，浅色设计便于找物。
- 尺寸：高 45cm × 宽 30cm × 厚 18cm，重量 1.1kg。
- 电脑仓：独立悬浮仓，可容纳 16 英寸笔记本，四周加厚防震。
- 分区：主仓、电脑仓、平板仓、前幅快取袋、两侧弹性水杯袋、背部防盗暗袋。
- 背负：S 型透气肩带 + 蜂窝背板 + 可调节胸带，支持行李箱拉杆固定带。

## 使用场景
- 通勤：可放入 16 英寸笔记本、A4 文件、雨伞与水杯。
- 短途出差：26L 容量满足 2-3 天衣物收纳，可固定在行李箱上。
- 骑行：反光条设计提升夜间安全性，胸带减少晃动。

## 清洁与保养
- 日常用湿布擦拭即可，顽固污渍可用软毛刷蘸中性洗涤剂轻刷。
- 不可机洗、不可暴晒，阴凉通风处晾干。
- 避免接触油污与尖锐物品，防止涂层破损。

## 售后说明
支持 7 天无理由退换，需保持吊牌完整、无使用痕迹。拉链、扣具等五金件保修 1 年。
""",
            "服饰鞋包尺码与退换政策.md": """# 服饰鞋包尺码与退换政策

## 尺码对照
### 女士风衣
- XS：身高 150-155cm，体重 40-47kg，胸围 80-84cm
- S：身高 155-160cm，体重 47-53kg，胸围 84-88cm
- M：身高 160-165cm，体重 53-60kg，胸围 88-92cm
- L：身高 165-170cm，体重 60-68kg，胸围 92-96cm
- XL：身高 170-175cm，体重 68-75kg，胸围 96-100cm
- 版型微宽松，喜欢修身效果可选小一码。

### 双肩包
均码，适合身高 155-190cm 人群，肩带可调节范围 45-95cm。

## 退换货规则
- 自签收之日起 7 天内支持无理由退换，商品需吊牌完整、未洗涤、无穿着痕迹、无污渍与异味。
- 服饰类商品因尺码不合适退换，往返运费由消费者承担；质量问题由商家承担。
- 特价清仓、定制刻字、已拆封的内衣袜类不支持无理由退换。
- 换货可申请同款不同尺码或颜色，库存不足时可退款。

## 尺码建议
- 介于两个尺码之间时，风衣建议选大一码以便内搭；双肩包为均码无需担心。
- 如不确定尺码，可在下单前咨询在线客服，提供身高体重与常穿尺码获取建议。
- 收到商品后建议先试穿并保留吊牌，确认合适后再剪标。
""",
        },
    },
]


async def ensure_demo_user() -> None:
    async with SessionLocal() as db:
        existing = (
            await db.execute(select(User).where(User.username == "demo"))
        ).scalar_one_or_none()
        if existing:
            return
        db.add(User(username="demo", password_hash=hash_password("demo123"), role="user"))
        await db.commit()
        print("已创建演示用户 demo / demo123")


async def ensure_kb(spec: dict) -> KnowledgeBase:
    async with SessionLocal() as db:
        kb = (
            await db.execute(select(KnowledgeBase).where(KnowledgeBase.name == spec["name"]))
        ).scalar_one_or_none()
        if kb:
            return kb
        kb = KnowledgeBase(name=spec["name"], description=spec["description"])
        db.add(kb)
        await db.commit()
        await db.refresh(kb)
        print(f"已创建知识库：{kb.name}")
        return kb


async def seed_doc(kb: KnowledgeBase, filename: str, content: str) -> None:
    async with SessionLocal() as db:
        existing = (
            await db.execute(
                select(Document).where(Document.kb_id == kb.id, Document.filename == filename)
            )
        ).scalar_one_or_none()
        if existing:
            print(f"跳过已存在文档：{filename}")
            return

        doc_id = new_id()
        target_dir = settings.uploads_dir / kb.id
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{doc_id}.md"
        path.write_text(content, encoding="utf-8")

        doc = Document(
            id=doc_id,
            kb_id=kb.id,
            filename=filename,
            stored_path=str(path),
            file_hash=f"seed-{doc_id}",
            mime="text/markdown",
            size=len(content.encode("utf-8")),
            status="pending",
        )
        task = IngestionTask(
            id=new_id(), doc_id=doc_id, stage="pending", progress=0, status="running"
        )
        db.add(doc)
        db.add(task)
        await db.commit()
        task_id = task.id

    print(f"开始入库：{filename}")
    await ingest_document(doc_id, task_id)
    print(f"入库完成：{filename}")


async def main() -> None:
    if not settings.dashscope_api_key:
        print("缺少 DASHSCOPE_API_KEY，请先配置环境变量或 .env 后再运行。")
        raise SystemExit(1)

    await init_db()
    await ensure_demo_user()
    for spec in KB_SPECS:
        kb = await ensure_kb(spec)
        for filename, content in spec["docs"].items():
            await seed_doc(kb, filename, content)
    print("演示数据准备完成。")
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
