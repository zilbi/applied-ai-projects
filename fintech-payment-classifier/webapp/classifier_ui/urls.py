from django.urls import path
from . import views
app_name='classifier_ui'
urlpatterns=[path('',views.home,name='home'),path('runs/new/',views.new_run,name='new_run'),path('runs/<uuid:run_id>/',views.run_detail,name='run_detail'),path('runs/<uuid:run_id>/companies/',views.company_list,name='company_list'),path('runs/<uuid:run_id>/companies/<str:company_id>/',views.company_detail,name='company_detail'),path('runs/<uuid:run_id>/download/<str:kind>/',views.download,name='download')]
