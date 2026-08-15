from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import ArtifactType, GeneratedArtifact, RiskEvent
from src.schemas import GenerateCSVRequest, GenerateReportRequest

OUTPUTS = Path("outputs")


async def generate_csv(session: AsyncSession, payload: GenerateCSVRequest) -> dict:
    OUTPUTS.mkdir(exist_ok=True)
    path = OUTPUTS / f"{payload.title}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["client", "metric_date", "nps", "comment"])
        for idx in range(payload.rows):
            writer.writerow([f"Demo Client {idx + 1}", datetime.now().date(), 6 + idx % 5, "synthetic"])
    artifact = GeneratedArtifact(artifact_type=ArtifactType.csv, title=payload.title, file_path=str(path))
    session.add(artifact)
    await session.commit()
    return {"file_path": str(path), "rows": payload.rows}


async def generate_risk_report(session: AsyncSession, payload: GenerateReportRequest) -> dict:
    OUTPUTS.mkdir(exist_ok=True)
    result = await session.execute(select(RiskEvent).order_by(RiskEvent.detected_at.desc()).limit(100))
    risks = list(result.scalars())
    path = OUTPUTS / f"{payload.title}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    lines = [
        "Risk report",
        f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
        f"Open risks: {len(risks)}",
        "",
    ]
    lines.extend([f"- [{risk.severity.value}] {risk.title}: {risk.recommended_action}" for risk in risks])
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas

        c = canvas.Canvas(str(path), pagesize=A4)
        _, height = A4
        y = height - 50
        for line in lines:
            c.drawString(40, y, line[:110])
            y -= 18
            if y < 50:
                c.showPage()
                y = height - 50
        c.save()
    except Exception:
        path = path.with_suffix(".txt")
        path.write_text("\n".join(lines), encoding="utf-8")
    artifact = GeneratedArtifact(
        user_id=payload.user_id,
        artifact_type=ArtifactType.pdf_report,
        title=payload.title,
        file_path=str(path),
        content_text="\n".join(lines),
    )
    session.add(artifact)
    await session.commit()
    return {"file_path": str(path), "risks": len(risks)}
