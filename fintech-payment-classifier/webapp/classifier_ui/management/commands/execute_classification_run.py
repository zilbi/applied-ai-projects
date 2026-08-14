from __future__ import annotations
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from classifier_ui.models import ClassificationRun
from classifier_ui.services import import_results
from fintech_classifier.full_pipeline import FullClassificationPipeline

class Command(BaseCommand):
    def add_arguments(self,p):
        p.add_argument('run_uuid')
        p.add_argument('--max-tavily-credits', type=int, default=None,
                       help='Total Tavily credit limit for this run.')
    def handle(self,*args,**opts):
        # A run owns one output directory and one research-store time window.
        # Concurrent invocations otherwise race and the slower, stale process
        # can overwrite a newer selected website with an old candidate.
        with transaction.atomic():
            try: run=ClassificationRun.objects.select_for_update().get(id=opts['run_uuid'])
            except ClassificationRun.DoesNotExist: raise CommandError('Run not found')
            if run.status in {ClassificationRun.Status.VALIDATING, ClassificationRun.Status.RUNNING}:
                raise CommandError('This run is already in progress. Wait for it to finish or create a new run.')
            if run.status == ClassificationRun.Status.COMPLETED:
                raise CommandError('This run is already complete. Create a new run to classify the file again.')
            run.status='VALIDATING';run.current_stage='validation';run.progress_percent=2;run.output_directory=str(Path(settings.PIPELINE_RESULTS_DIR)/str(run.id));run.save()
        root=Path(settings.PIPELINE_RESULTS_DIR); output=root/str(run.id)
        def progress(stage, done, total):
            run.current_stage=stage;run.companies_total=total;run.companies_processed=done;run.progress_percent=int(100*done/total) if total else 0;run.save(update_fields=['current_stage','companies_total','companies_processed','progress_percent','updated_at'])
        try:
            run.status='RUNNING';run.current_stage='classification';run.progress_percent=5;run.save()
            output.mkdir(parents=True,exist_ok=True); (output/'logs').mkdir(exist_ok=True); (output/'input').mkdir(exist_ok=True); (output/'intermediate').mkdir(exist_ok=True)
            result=FullClassificationPipeline(
                no_network=not run.external_network_enabled,
                progress=progress,
                max_tavily_credits=opts['max_tavily_credits'],
            ).run(run.stored_input_path,output)
            import_results(run,output/'output');run.status='COMPLETED';run.current_stage='completed';run.progress_percent=100;run.save()
        except Exception as exc:
            run.status='FAILED';run.error_message=f'{type(exc).__name__}: {exc}'[:1000];run.current_stage='failed';run.save();raise
