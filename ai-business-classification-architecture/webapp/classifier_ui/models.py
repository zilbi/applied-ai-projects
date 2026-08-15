import uuid
from django.db import models

class ClassificationRun(models.Model):
    class Status(models.TextChoices): CREATED='CREATED'; VALIDATING='VALIDATING'; RUNNING='RUNNING'; COMPLETED='COMPLETED'; FAILED='FAILED'; CANCELLED='CANCELLED'
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    created_at=models.DateTimeField(auto_now_add=True); updated_at=models.DateTimeField(auto_now=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.CREATED)
    original_filename=models.CharField(max_length=255); stored_input_path=models.CharField(max_length=1024); output_directory=models.CharField(max_length=1024,blank=True)
    progress_percent=models.PositiveSmallIntegerField(default=0); current_stage=models.CharField(max_length=120,blank=True)
    companies_total=models.PositiveIntegerField(default=0); companies_processed=models.PositiveIntegerField(default=0)
    auto_count=models.PositiveIntegerField(default=0); review_count=models.PositiveIntegerField(default=0); class_a_count=models.PositiveIntegerField(default=0); class_b_count=models.PositiveIntegerField(default=0); non_fintech_count=models.PositiveIntegerField(default=0)
    error_message=models.TextField(blank=True); external_network_enabled=models.BooleanField(default=True); model_name=models.CharField(max_length=128,blank=True); model_version=models.CharField(max_length=256,blank=True); feature_fingerprint=models.CharField(max_length=128,blank=True); run_report=models.JSONField(default=dict,blank=True)
    class Meta: ordering=['-created_at']

class CompanyResult(models.Model):
    run=models.ForeignKey(ClassificationRun,on_delete=models.CASCADE,related_name='companies')
    company_id=models.CharField(max_length=128); canonical_name=models.CharField(max_length=512,blank=True); inn=models.CharField(max_length=16,blank=True); operation_count=models.PositiveIntegerField(default=0)
    final_class=models.CharField(max_length=32); decision_status=models.CharField(max_length=32); final_confidence=models.FloatField(default=0)
    probability_a=models.FloatField(default=0); probability_b=models.FloatField(default=0); probability_non_fintech=models.FloatField(default=0); rule_score_a=models.FloatField(default=0); rule_score_b=models.FloatField(default=0); rule_score_non_fintech=models.FloatField(default=0); models_agree=models.BooleanField(default=False)
    site_url=models.CharField(max_length=1024,blank=True); site_status=models.CharField(max_length=64,blank=True); data_quality_score=models.FloatField(default=0); score_gap=models.FloatField(default=0); review_reasons=models.JSONField(default=list,blank=True); explanation=models.TextField(blank=True); evidence=models.JSONField(default=dict,blank=True)
    manual_override_class=models.CharField(max_length=32,blank=True,null=True); manual_override_comment=models.TextField(blank=True); manual_override_at=models.DateTimeField(blank=True,null=True)
    class Meta: unique_together=[('run','company_id')]; ordering=['-final_confidence','canonical_name']
    @property
    def original_final_class(self): return self.final_class
    @property
    def effective_final_class(self): return self.manual_override_class or self.final_class
    @property
    def manual_override_applied(self): return bool(self.manual_override_class)
    @property
    def site_status_label(self):
        return {
            'not_started': 'not evaluated in this run',
            'success': 'pages loaded',
            'timeout': 'request timed out',
            'blocked_by_waf': 'website blocked the automated request',
            'http_401': 'authentication required',
            'http_403': 'access denied',
            'http_404': 'page not found',
            'http_498': 'request rejected by website protection',
            'not_found': 'website not found',
        }.get(self.site_status or '', self.site_status or 'not evaluated')
