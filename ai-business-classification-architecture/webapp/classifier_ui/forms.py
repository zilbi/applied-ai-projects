from pathlib import Path
from django import forms
from django.conf import settings
from .models import CompanyResult
class RunUploadForm(forms.Form):
    file=forms.FileField(label='XLSX or CSV')
    def clean_file(self):
        f=self.cleaned_data['file']; suffix=Path(f.name).suffix.lower()
        if suffix not in {'.xlsx','.csv'}: raise forms.ValidationError('Only XLSX and CSV files are supported.')
        if f.size>settings.MAX_UPLOAD_MB*1024*1024: raise forms.ValidationError('The file exceeds the maximum upload size.')
        head=f.read(8); f.seek(0)
        if suffix=='.xlsx' and not head.startswith(b'PK'): raise forms.ValidationError('The file does not appear to be a valid XLSX workbook.')
        return f
class ManualOverrideForm(forms.Form):
    manual_override_class=forms.ChoiceField(choices=[('A','A'),('B','B'),('NON_FINTECH','NON_FINTECH'),('REVIEW','REVIEW')])
    manual_override_comment=forms.CharField(required=False,widget=forms.Textarea)
