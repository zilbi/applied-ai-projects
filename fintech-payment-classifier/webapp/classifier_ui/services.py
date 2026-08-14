from __future__ import annotations
import json, os, subprocess, sys, uuid
from pathlib import Path
from django.conf import settings
from .models import ClassificationRun,CompanyResult


def pipeline_python() -> str:
    """Return a usable interpreter for the background classification job.

    ``PYTHON_EXECUTABLE`` is optional.  A stale value such as ``/bin/python``
    must never make an uploaded run fail before its log is created.
    """
    configured = os.environ.get("PYTHON_EXECUTABLE", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return sys.executable

def save_upload(upload) -> Path:
    target=Path(settings.UPLOAD_DIR); target.mkdir(parents=True,exist_ok=True)
    suffix=Path(upload.name).suffix.lower(); path=target/f'{uuid.uuid4().hex}{suffix}'
    with path.open('wb') as out:
        for chunk in upload.chunks(): out.write(chunk)
    return path

def start_run(run: ClassificationRun) -> None:
    root=Path(settings.BASE_DIR) if hasattr(settings,'BASE_DIR') else Path(__file__).resolve().parents[2]
    manage=root/'webapp'/'manage.py'; log=Path(settings.PIPELINE_RESULTS_DIR)/str(run.id)/'logs'/'django_subprocess.log'; log.parent.mkdir(parents=True,exist_ok=True)
    executable=pipeline_python()
    with log.open('ab') as handle:
        subprocess.Popen([executable,str(manage),'execute_classification_run',str(run.id)],shell=False,stdout=handle,stderr=subprocess.STDOUT,cwd=str(root))

def import_results(run: ClassificationRun, output: Path) -> None:
    rows=json.loads((output/'company_results.json').read_text(encoding='utf-8'))
    CompanyResult.objects.filter(run=run).delete()
    items=[]
    for row in rows:
        items.append(CompanyResult(run=run,company_id=str(row['company_id']),canonical_name=row.get('canonical_company_name',''),inn=row.get('inn',''),operation_count=row.get('operation_count',0),final_class=row.get('final_class','REVIEW'),decision_status=row.get('decision_status','MANUAL_REVIEW'),final_confidence=row.get('final_confidence',0),probability_a=row.get('probability_A',0),probability_b=row.get('probability_B',0),probability_non_fintech=row.get('probability_NON_FINTECH',0),rule_score_a=row.get('rule_score_A',0),rule_score_b=row.get('rule_score_B',0),rule_score_non_fintech=row.get('rule_score_NON_FINTECH',0),models_agree=row.get('models_agree',False),site_url=row.get('site_url',''),site_status=row.get('site_fetch_status',''),data_quality_score=row.get('data_quality_score',0),score_gap=row.get('score_gap',0),review_reasons=row.get('review_reasons',[]),explanation=row.get('explanation',''),evidence=row))
    CompanyResult.objects.bulk_create(items)
    report=json.loads((output/'run_report.json').read_text(encoding='utf-8'))
    distribution=report.get('class_distribution',{})
    run.companies_total=len(items);run.companies_processed=len(items);run.auto_count=report.get('auto_count',0);run.review_count=report.get('review_count',0);run.class_a_count=distribution.get('A',0);run.class_b_count=distribution.get('B',0);run.non_fintech_count=distribution.get('NON_FINTECH',0);run.model_name=report.get('model',{}).get('name','');run.model_version=report.get('model',{}).get('version','');run.feature_fingerprint=report.get('model',{}).get('feature_fingerprint','');run.run_report=report
