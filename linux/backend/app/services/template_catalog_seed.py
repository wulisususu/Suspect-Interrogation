"""Initial operator-editable templates; learned counts are deliberately zero."""


def _template(id, key, title, category, tag, tone, summary, minutes, scene, elements, questions, badge=None):
    catalog = dict(id=id, backendKey=key, title=title, category=category, tag=tag, tagTone=tone,
                   summary=summary, minutes=minutes, scene=scene, learnedCount=0)
    if badge:
        catalog['badge'] = dict(label=badge[0], tone=badge[1])
    structure = dict(elements=[dict(key=k, label=label) for k, label in elements],
                     questions=[dict(key=f'body-{i}', text=text, elementKey=element_key)
                                for i, (text, element_key) in enumerate(questions, 1)])
    return catalog, structure


SEED_TEMPLATES = [
    _template('theft-ebike', 'THEFT_EBIKE_V1', '盗窃（电动车）', 'theft', '盗窃', 'primary',
              '案发时间地点、车辆特征、锁具情况、最后见到时间、可疑对象、车辆价值', 15, '报案大厅 / 被害人',
              [('time_place', '案发时间与地点'), ('vehicle', '车辆品牌 / 颜色 / 购买时间'), ('lock', '锁具情况（遥控锁 / U 型锁）'), ('last_seen', '最后见到车辆的时间'), ('witness', '可疑对象与目击情况'), ('value', '车辆价值与发票凭证')],
              [('请讲一下事情经过？', 'time_place'), ('车辆什么品牌、颜色？', 'vehicle'), ('当时锁了吗？', 'lock'), ('你最后一次看到车是什么时候？', 'last_seen'), ('有没有看到可疑人员？', 'witness'), ('车辆购置价值大约多少？', 'value')], ('推荐', 'danger')),
    _template('theft-vehicle-goods', 'THEFT_VEHICLE_GOODS_V1', '盗窃（车内财物）', 'theft', '盗窃', 'primary',
              '停车位置、车门锁闭情况、财物清单与价值、发现经过、监控覆盖情况', 18, '报案大厅 / 被害人',
              [('time_place', '停车时间与位置'), ('vehicle', '车辆信息'), ('lock', '车门锁闭情况'), ('goods', '被盗财物清单'), ('value', '财物价值'), ('discovery', '发现经过'), ('surveillance', '监控覆盖情况')],
              [('车停在什么位置？', 'time_place'), ('双方车辆的基本信息？', 'vehicle'), ('下车时车门锁好了吗？', 'lock'), ('车内少了哪些东西？', 'goods'), ('这些东西大约值多少钱？', 'value'), ('什么时候发现被盗的？', 'discovery'), ('附近有没有监控？', 'surveillance')]),
    _template('injury-assault', 'INJURY_ASSAULT_V1', '故意伤害（殴打他人）', 'injury', '伤害', 'danger',
              '起因经过、伤情与就医、致伤工具、在场证人、双方关系、调解意愿', 25, '被害人 / 证人',
              [('time_place', '案发时间与地点'), ('cause', '事情起因'), ('process', '经过'), ('injury', '伤情与就医'), ('tool', '致伤工具'), ('witness', '在场证人'), ('relationship', '双方关系'), ('mediation', '调解意愿')],
              [('事情发生在什么时间、什么地点？', 'time_place'), ('双方因为什么起的冲突？', 'cause'), ('请讲一下事情经过？', 'process'), ('你哪里受了伤，去医院了吗？', 'injury'), ('对方用什么打的你？', 'tool'), ('当时有谁在场？', 'witness'), ('你们之前认识吗？', 'relationship'), ('是否愿意调解？', 'mediation')]),
    _template('traffic-simple', 'TRAFFIC_SIMPLE_V1', '交通事故（简易处理）', 'traffic', '交通', 'warning',
              '事故时间地点、双方车辆、责任认定、损失情况、保险信息', 10, '交警简易处理',
              [('time_place', '事故时间与地点'), ('vehicles', '双方车辆信息'), ('process', '事故经过与责任'), ('loss', '损失情况'), ('insurance', '保险信息')],
              [('事故在什么时间、什么地点发生？', 'time_place'), ('双方各是什么车？', 'vehicles'), ('事故是怎么发生的？', 'process'), ('车辆和人员损失情况如何？', 'loss'), ('双方投保了哪家保险？', 'insurance')], ('最快', 'success')),
    _template('report-general', 'REPORT_GENERAL_V1', '报案登记（通用）', 'other', '通用', 'neutral',
              '报案人身份、案由、事情经过、诉求与联系方式，任何案由均可起步', 8, '任何场景',
              [('reporter', '报案人身份'), ('reason', '案由'), ('process', '事情经过'), ('contact_request', '诉求与联系方式')],
              [('你的基本身份情况？', 'reporter'), ('你要报什么案？', 'reason'), ('请讲一下事情经过？', 'process'), ('你希望公安机关怎么处理？怎么联系到你？', 'contact_request')]),
    _template('suspect-inquiry', 'SUSPECT_INQUIRY_V1', '嫌疑人询问', 'other', '其他', 'neutral',
              '讯问策略引导、认罪认罚、退赃退赔、前科劣迹、同案关系、作案工具去向', 40, '办案区 / 嫌疑人',
              [('time', '时间'), ('place', '地点'), ('motive', '动机 / 目的'), ('method', '手段 / 工具'), ('process', '行为经过'), ('evidence', '证据对应'), ('after', '事后处置 / 后果')],
              [('事情发生在什么时间？', 'time'), ('事情发生在什么地点？', 'place'), ('你为什么这样做？', 'motive'), ('使用了什么手段或工具？', 'method'), ('请讲述具体行为经过？', 'process'), ('相关证据与你的行为有什么关系？', 'evidence'), ('事后如何处置，造成什么后果？', 'after')], ('自助式不适用', 'warning')),
]
