"""Leak-safe multiclass Logistic Regression baseline, entirely local."""
from __future__ import annotations
import json, platform, warnings
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, classification_report, confusion_matrix, f1_score, log_loss, precision_recall_fscore_support
from sklearn.model_selection import GridSearchCV, RepeatedStratifiedKFold, StratifiedKFold, cross_val_score, train_test_split
from sklearn.exceptions import ConvergenceWarning
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

CLASSES=["A","B","NON_FINTECH"]; CS=[.01,.1,.3,1.,3.,10.]
FORBIDDEN=("target","gold_segment","inn","ogrn","account","bic","corr_account","operation_id","website_hypothesis","rule_based_class","predicted_class","source_row","source_sheet")

def load_data(root: str|Path):
 root=Path(root); ml=root/'results/ml'
 x=pd.read_csv(ml/'train_company_features.csv',dtype={"company_id":str}); y=pd.read_csv(ml/'train_company_targets.csv',dtype={"company_id":str})
 p=pd.read_csv(ml/'predict_company_features.csv',dtype={"company_id":str}); corpus=pd.read_csv(root/'results/company_text_corpus.csv',dtype={"company_id":str}).fillna("")
 if x.company_id.duplicated().any() or y.company_id.duplicated().any(): raise ValueError('company_id не уникален')
 d=x.merge(y[['company_id','target_class','target_status']],on='company_id',how='inner',validate='one_to_one'); d=d[d.target_status.eq('confirmed')].copy()
 if set(d.target_class)-set(CLASSES): raise ValueError('недопустимый target')
 if set(x.columns)!=set(p.columns): raise ValueError('train/predict feature columns differ')
 if d.feature_version.nunique()!=1 or p.feature_version.nunique()!=1 or d.feature_version.iloc[0]!=p.feature_version.iloc[0]: raise ValueError('feature_version mismatch')
 def text(frame):
  z=frame.merge(corpus,on='company_id',how='left').fillna("")
  cols=[c for c in ['clean_company_name','payment_purposes','registry_description','website_text','website_keyphrases'] if c in z]
  return z.assign(model_text=z.apply(lambda r:' '.join(f'[{c.upper()}] {r[c]}' for c in cols if str(r[c]).strip()),axis=1))
 d,p=text(d),text(p); features=[c for c in x.columns if c not in {'company_id','feature_version','calculated_at'}]
 for frame in (d,p):
  for column in features:
   if not pd.api.types.is_numeric_dtype(frame[column]): frame[column]=frame[column].fillna('').astype(str)
 leaked=[c for c in features if c.lower() in FORBIDDEN or c.lower().startswith(("gold_","target_","predicted_"))]
 if leaked: raise ValueError(f'leakage: {leaked}')
 return d,p,features

def pipeline(frame, features, experiment):
 nums=[c for c in features if pd.api.types.is_numeric_dtype(frame[c])]
 cats=[c for c in features if c not in nums]
 parts=[]
 if experiment!='text_only':
  if nums: parts.append(('num',Pipeline([('impute',SimpleImputer(strategy='median')),('scale',StandardScaler(with_mean=False))]),nums))
  if cats: parts.append(('cat',Pipeline([('impute',SimpleImputer(strategy='most_frequent')),('onehot',OneHotEncoder(handle_unknown='ignore'))]),cats))
 if experiment!='structured_only':
  parts += [('word',TfidfVectorizer(analyzer='word',ngram_range=(1,2),min_df=2,max_df=.98,sublinear_tf=True,max_features=30000,lowercase=True),'model_text'),('char',TfidfVectorizer(analyzer='char_wb',ngram_range=(3,5),min_df=2,sublinear_tf=True,max_features=30000,lowercase=True),'model_text')]
 return Pipeline([('preprocess',ColumnTransformer(parts)),('model',LogisticRegression(solver='saga',l1_ratio=0,class_weight='balanced',max_iter=10000,tol=1e-3,random_state=42))])

def metrics(y, pred, proba, classes):
 pp,rr,ff,_=precision_recall_fscore_support(y,pred,labels=classes,zero_division=0)
 out={'accuracy':accuracy_score(y,pred),'balanced_accuracy':balanced_accuracy_score(y,pred),'macro_f1':f1_score(y,pred,average='macro'),'weighted_f1':f1_score(y,pred,average='weighted'),'log_loss':log_loss(y,proba,labels=classes)}
 for i,c in enumerate(classes): out[f'{c}_precision']=pp[i];out[f'{c}_recall']=rr[i];out[f'{c}_f1']=ff[i]
 return out

def run(root, test_size=.2, random_state=42, experiments=('structured_only','text_only','combined'), save=True):
 import joblib, sklearn
 d,p,features=load_data(root); ids=d.company_id.to_numpy(); y=d.target_class.to_numpy()
 tr,te=train_test_split(np.arange(len(d)),test_size=test_size,random_state=random_state,stratify=y)
 if set(ids[tr])&set(ids[te]): raise ValueError('split overlap')
 out=Path(root)/'results/ml/logreg'; out.mkdir(parents=True,exist_ok=True)
 split={'random_state':random_state,'test_size':test_size,'train_company_id':ids[tr].tolist(),'test_company_id':ids[te].tolist(),'class_distribution':d.target_class.value_counts().to_dict()}
 results=[]; allpred=[]; coeff=[]; fitted={}
 for exp in experiments:
  base=pipeline(d,features,exp); folds=min(5,min(pd.Series(y[tr]).value_counts()))
  grid=GridSearchCV(base,{'model__C':CS},scoring='f1_macro',cv=StratifiedKFold(folds,shuffle=True,random_state=random_state),n_jobs=1)
  grid.fit(d.iloc[tr],y[tr]); model=grid.best_estimator_; pred=model.predict(d.iloc[te]); pro=model.predict_proba(d.iloc[te]); m=metrics(y[te],pred,pro,model.classes_); m.update(experiment=exp,best_C=grid.best_params_['model__C'],cv_macro_f1=grid.best_score_)
  dummy=DummyClassifier(strategy='most_frequent').fit(d.iloc[tr],y[tr]);m['dummy_accuracy']=accuracy_score(y[te],dummy.predict(d.iloc[te]));results.append(m);fitted[exp]=model
  for i,c in enumerate(model.classes_):
   for rank,j in enumerate(np.argsort(model.named_steps['model'].coef_[i])[-20:][::-1],1): coeff.append({'experiment':exp,'class':c,'feature_name':model.named_steps['preprocess'].get_feature_names_out()[j],'coefficient':model.named_steps['model'].coef_[i,j],'feature_source':str(model.named_steps['preprocess'].get_feature_names_out()[j]).split('__')[0],'rank':rank})
  for k,ix in enumerate(te):
   probs=dict(zip(model.classes_,pro[k])); ordered=sorted(probs.values(),reverse=True);allpred.append({'experiment':exp,'company_id':ids[ix],'true_class':y[ix],'predicted_class':pred[k],**{f'probability_{c}':probs.get(c,0) for c in CLASSES},'top_probability':ordered[0],'second_probability':ordered[1],'probability_margin':ordered[0]-ordered[1],'is_correct':int(pred[k]==y[ix])})
  joblib.dump(model,out/f'{exp}_pipeline.joblib')
 best=sorted(results,key=lambda r:(-r['macro_f1'],-r['balanced_accuracy'],r['experiment']))[0]; prod=pipeline(d,features,best['experiment']);prod.set_params(model__C=best['best_C']);prod.fit(d,y);joblib.dump(prod,out/'best_logreg_pipeline.joblib')
 best_rows=[row for row in allpred if row['experiment']==best['experiment']]
 pd.DataFrame(confusion_matrix([row['true_class'] for row in best_rows],[row['predicted_class'] for row in best_rows],labels=CLASSES),index=CLASSES,columns=CLASSES).to_csv(out/'confusion_matrix.csv')
 pd.DataFrame(classification_report([row['true_class'] for row in best_rows],[row['predicted_class'] for row in best_rows],labels=CLASSES,output_dict=True,zero_division=0)).T.to_csv(out/'classification_report.csv')
 pro=prod.predict_proba(p); pred=prod.predict(p); rows=[]
 for i,cid in enumerate(p.company_id):
  probs=dict(zip(prod.classes_,pro[i]));ordered=sorted(probs.values(),reverse=True);rows.append({'company_id':cid,'predicted_class':pred[i],**{f'probability_{c}':probs.get(c,0) for c in CLASSES},'top_probability':ordered[0],'probability_margin':ordered[0]-ordered[1],'low_confidence_flag':int(ordered[0]<.6),'low_margin_flag':int(ordered[0]-ordered[1]<.15),'model_name':'logistic_regression','model_version':'logreg-v1'})
 pd.DataFrame(results).to_csv(out/'experiment_comparison.csv',index=False);pd.DataFrame(allpred).to_csv(out/'holdout_predictions.csv',index=False);pd.DataFrame(rows).to_csv(out/'predict_company_predictions.csv',index=False);pd.DataFrame(coeff).to_csv(out/'top_coefficients.csv',index=False);(out/'split.json').write_text(json.dumps(split,ensure_ascii=False,indent=2));(out/'metrics.json').write_text(json.dumps(results,ensure_ascii=False,indent=2));(out/'model_metadata.json').write_text(json.dumps({'model':'multiclass_logistic_regression','classes':CLASSES,'feature_version':d.feature_version.iloc[0],'structured_features':len(features),'best_experiment':best['experiment'],'best_C':best['best_C'],'holdout_metrics':best,'python':platform.python_version(),'sklearn':sklearn.__version__},ensure_ascii=False,indent=2));return d,p,results,best


def repeated_structured_evaluation(root: str | Path, *, random_states=range(20), test_size=.20):
 """Evaluate the unchanged structured-only baseline on independent holdouts.

 The function intentionally reads only labelled data.  Each C search and every
 vector/preprocessing fit is limited to the corresponding train fold.
 """
 root=Path(root); d,_,features=load_data(root); y=d.target_class.to_numpy(); ids=d.company_id.to_numpy()
 rows=[]; details=[]
 for seed in random_states:
  tr,te=train_test_split(np.arange(len(d)),test_size=test_size,random_state=seed,stratify=y)
  if set(ids[tr]) & set(ids[te]): raise AssertionError('company_id overlap')
  folds=min(5,int(pd.Series(y[tr]).value_counts().min()))
  base=pipeline(d,features,'structured_only')
  grid=GridSearchCV(base,{'model__C':CS},scoring='f1_macro',cv=StratifiedKFold(folds,shuffle=True,random_state=seed),n_jobs=1)
  with warnings.catch_warnings(record=True) as caught:
   warnings.simplefilter('always',ConvergenceWarning); grid.fit(d.iloc[tr],y[tr])
  model=grid.best_estimator_; pred=model.predict(d.iloc[te]); pro=model.predict_proba(d.iloc[te])
  metric=metrics(y[te],pred,pro,model.classes_)
  cm=confusion_matrix(y[te],pred,labels=CLASSES)
  error_ids=ids[te][pred != y[te]].tolist()
  row={'random_state':seed,'train_size':len(tr),'test_size':len(te),'best_C':grid.best_params_['model__C'],'cv_macro_f1':grid.best_score_,'convergence_warning':any(issubclass(w.category,ConvergenceWarning) for w in caught),'errors':len(error_ids),'error_company_ids':json.dumps(error_ids,ensure_ascii=False),'train_class_distribution':json.dumps(pd.Series(y[tr]).value_counts().to_dict(),ensure_ascii=False),'test_class_distribution':json.dumps(pd.Series(y[te]).value_counts().to_dict(),ensure_ascii=False),**metric}
  rows.append(row); details.append({**row,'confusion_matrix':cm.tolist(),'test_company_ids':ids[te].tolist()})
 df=pd.DataFrame(rows)
 # Repeated CV is calculated on all labelled companies, without a held-out set;
 # it is an additional stability diagnostic, not a replacement for holdouts.
 folds=min(5,int(pd.Series(y).value_counts().min()))
 cv=RepeatedStratifiedKFold(n_splits=folds,n_repeats=5,random_state=42)
 cv_model=pipeline(d,features,'structured_only'); cv_model.set_params(model__C=.01)
 with warnings.catch_warnings(record=True) as caught:
  warnings.simplefilter('always',ConvergenceWarning)
  cv_scores=cross_val_score(cv_model,d,y,cv=cv,scoring='f1_macro',n_jobs=1)
 confusion_totals=np.zeros((3,3),dtype=int)
 for item in details: confusion_totals += np.array(item['confusion_matrix'])
 summary={'splits':len(df),'macro_f1_mean':float(df.macro_f1.mean()),'macro_f1_std':float(df.macro_f1.std(ddof=0)),'macro_f1_median':float(df.macro_f1.median()),'macro_f1_min':float(df.macro_f1.min()),'macro_f1_max':float(df.macro_f1.max()),'macro_f1_p25':float(df.macro_f1.quantile(.25)),'macro_f1_p75':float(df.macro_f1.quantile(.75)),'accuracy_mean':float(df.accuracy.mean()),'A_f1_mean':float(df.A_f1.mean()),'B_f1_mean':float(df.B_f1.mean()),'NON_FINTECH_f1_mean':float(df.NON_FINTECH_f1.mean()),'A_as_B':int(confusion_totals[0,1]),'B_as_A':int(confusion_totals[1,0]),'fintech_as_non_fintech':int(confusion_totals[0,2]+confusion_totals[1,2]+confusion_totals[2,0]+confusion_totals[2,1]),'repeated_cv':{'n_splits':folds,'n_repeats':5,'scores':cv_scores.tolist(),'mean_macro_f1':float(cv_scores.mean()),'std_macro_f1':float(cv_scores.std(ddof=0))},'repeated_cv_convergence_warning':any(issubclass(w.category,ConvergenceWarning) for w in caught)}
 error_counts={}
 for value in df.error_company_ids:
  for cid in json.loads(value): error_counts[str(cid)]=error_counts.get(str(cid),0)+1
 summary['most_frequent_errors']=[{'company_id':k,'error_count':v} for k,v in sorted(error_counts.items(),key=lambda i:(-i[1],i[0]))]
 out=root/'results/ml/logreg'; out.mkdir(parents=True,exist_ok=True)
 df.to_csv(out/'repeated_splits.csv',index=False)
 (out/'repeated_splits.json').write_text(json.dumps({'summary':summary,'splits':details},ensure_ascii=False,indent=2))
 return df,summary
