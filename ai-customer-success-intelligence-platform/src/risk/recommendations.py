from src.models import RiskType


def recommendation_for(risk_type: RiskType) -> str:
    mapping = {
        RiskType.health_drop: "Назначить health-check созвон и согласовать план восстановления.",
        RiskType.payment_delay: "Связаться с финансовым контактом и уточнить причину просадки оплат.",
        RiskType.low_activity: "Запустить adoption-план для ключевых пользователей.",
        RiskType.negative_sentiment: "Провести разговор с decision maker и зафиксировать причины недовольства.",
        RiskType.high_churn_probability: "Создать антикризисный success-plan с контрольной датой.",
        RiskType.no_contact: "Назначить контакт в ближайшие 48 часов.",
        RiskType.nps_drop: "Разобрать detractor feedback и предложить конкретное улучшение.",
    }
    return mapping[risk_type]
