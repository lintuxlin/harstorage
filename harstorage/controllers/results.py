from harstorage.lib.HAR import HAR
from harstorage.lib.MongoHandler import MongoDB

import logging
import json
import os
import hashlib
from mimetypes import guess_type
from time import strftime, localtime

from pylons import request, response, tmpl_context as c
from pylons import config
from pylons.controllers.util import redirect

from harstorage.lib.base import BaseController, render

log = logging.getLogger(__name__)

class ResultsController(BaseController):
    def index(self):
        # Version for static content
        c.rev = config['app_conf']['static_version']

        # MongoDB handler
        mdb_handler = MongoDB()
        
        # Initial row count
        c.rowcount = 0
        
        # Result table canvas
        c.metrics_table = list()
        for i in range(7):
            c.metrics_table.append(list())
        
        # Result aggregation based on unique label and latest timestamp
        latest_results = mdb_handler.collection.group(
            key=['label'],
            condition=None,
            initial={"timestamp":'1970-01-01 01:00:00'},
            reduce="\
                function(doc, prev) {                       \
                    if ( doc.timestamp > prev.timestamp ) { \
                        prev.timestamp = doc.timestamp;     \
                    }                                       \
                }"
        )
        
        # Populate result table with latest results
        for set in latest_results:
            result = mdb_handler.collection.find_one({'label':set['label'],'timestamp':set['timestamp']})
            
            c.metrics_table[0].append( result['label']                          )
            c.metrics_table[1].append( result['url']                            )
            c.metrics_table[2].append( result['ps_scores']['Total Score']       )
            c.metrics_table[3].append( result["total_size"]                     )
            c.metrics_table[4].append( result["requests"]                       )
            c.metrics_table[5].append( round(result["full_load_time"]/1000.0,1) )
            c.metrics_table[6].append( result["timestamp"]                      )
            
            c.rowcount += 1
        
        return render('./home.html')
    
    def details(self):
        # Version for static content
        c.rev = config['app_conf']['static_version']

        # Try to fetch details for URL
        try:
            c.url = request.GET['url']
            self.selectors(None,c.url)
            c.mode  = 'url'
            c.label = c.url
        # Use Label instead of URL
        except:
            c.label = request.GET['label']
            self.selectors(c.label,None)
            c.mode  = 'label'
            c.url   = c.label
 
        return render('./details.html')
    
    def selectors(self,label,url):
        # MongoDB handler
        mdb_handler = MongoDB()
        
        # Timestamps for selector
        c.timestamp     = list()

        # Querying data for timeline
        if label is not None:
            for result in mdb_handler.collection.find({"label":label}).sort("timestamp",-1):
                c.timestamp.append(result["timestamp"])
            c.query  = "/superposed/display?"
            c.query += "step_1_label=" + label
            c.query += "&step_1_start_ts=" + min(c.timestamp)
            c.query += "&step_1_end_ts=" + max(c.timestamp)
        else:
            for result in mdb_handler.collection.find({"url":url}).sort("timestamp",-1):
                c.timestamp.append(result["timestamp"])
            c.query = 'None'

    def timeline(self):
        # Options
        url     = request.GET['url']
        label   = request.GET['label']
        mode    = request.GET['mode']
        
        # MongoDB handler
        mdb_handler = MongoDB()
        
        # 5 Arrays for timeline chart
        ts_points       = str()
        time_points     = str()
        size_points     = str()
        req_points      = str()
        score_points    = str()
        
        # Querying data for timeline
        if mode == 'label':
            for result in mdb_handler.collection.find({"label":label}).sort("timestamp",1):
                ts_points       += str(result["timestamp"])+"#"
                time_points     += str(round(result["full_load_time"]/1000.0,1))+"#"
                size_points     += str(result["total_size"])+"#"
                req_points      += str(result["requests"])+"#"
                score_points    += str(result['ps_scores']['Total Score'])+"#"
        else:
            for result in mdb_handler.collection.find({"url":url}).sort("timestamp",1):
                ts_points       += str(result["timestamp"])+"#"
                time_points     += str(round(result["full_load_time"]/1000.0,1))+"#"
                size_points     += str(result["total_size"])+"#"
                req_points      += str(result["requests"])+"#"
                score_points    += str(result['ps_scores']['Total Score'])+"#"

        return ts_points[:-1]+";"\
                +time_points[:-1]+";"\
                +size_points[:-1]+";"\
                +req_points[:-1]+";"\
                +score_points[:-1]

    def runinfo(self):
        # MongoDB handler
        mdb_handler = MongoDB()
        
        # Timestamp from request
        timestamp = request.GET['timestamp']

        # MongoDB query
        test_results = mdb_handler.collection.find_one({"timestamp":timestamp})
        
        # HAR initialization
        har     = HAR(test_results['har'])
        har_id  = str(test_results['_id'])
        har.analyze()

        # Summary stats
        summary = { 'full_load_time'        :test_results['full_load_time'],
                    'onload_event'          :har.onload_event,
                    'start_render_time'     :har.start_render_time,
                    'time_to_first_byte'    :har.time_to_first_byte,
                    'total_dns_time'        :har.total_dns_time,
                    'total_transfer_time'   :har.total_transfer_time,
                    'total_server_time'     :har.total_server_time,
                    'avg_connecting_time'   :har.avg_connecting_time,
                    'avg_blocking_time'     :har.avg_blocking_time,
                    'total_size'            :test_results['total_size'],
                    'text_size'             :har.text_size,
                    'media_size'            :har.media_size,
                    'cache_size'            :har.cache_size,
                    'requests'              :test_results['requests'],
                    'redirects'             :har.redirects,
                    'bad_requests'          :har.bad_requests,
                    'domains'               :len(har.domains)
        }

        # Domains
        domains_req_ratio = dict()
        domains_weight_ratio = dict()

        for key,value in har.domains.items():
            domains_req_ratio[key] = value[0]
            domains_weight_ratio[key] = value[1]
        
        # Page Speed Scores
        scores = dict()
        
        for rule,score in test_results['ps_scores'].items():
            scores[rule] = score
        
        # Data for HAR Viewer
        filename = os.path.join( config['app_conf']['temp_store'], har_id )
        file = open(filename, 'w')
        file.write( test_results['har'].encode('utf-8') )
        file.close()

        # Final JSON
        return json.dumps({'summary'    :summary,
                           'pagespeed'  :scores,
                           'weights'    :har.weight_ratio(),
                           'requests'   :har.req_ratio(),
                           'd_weights'  :domains_weight_ratio,
                           'd_requests' :domains_req_ratio,
                           'har'        :har_id,
                            })
        
    def harviewer(self):
        # HAR Viewer customization
        response.set_cookie('phaseInterval', '-1')

        return render('./harviewer.html')
    
    def deleterun(self):
        # MongoDB handler
        mdb_handler = MongoDB()
        
        # Request parameters
        label       = request.GET['label']
        timestamp   = request.GET['timestamp']
        mode        = request.GET['mode']

        if request.GET['all'] == 'true':
            all = True
        else:
            all = False
            
        # Remove document from collection
        if mode == 'label':
            if all:
                mdb_handler.collection.remove({"label":label})
            else:
                mdb_handler.collection.remove({"label":label,"timestamp":timestamp})
            count = mdb_handler.collection.find({"label":label}).count()
        else:
            if all:
                mdb_handler.collection.remove({"url":label})
            else:
                mdb_handler.collection.remove({"url":label,"timestamp":timestamp})
            count = mdb_handler.collection.find({"url":label}).count()

        if count:
            return ("details?",mode,'=',label)
        else:
            return ("/")

    def upload(self):
        # Version for static content
        c.rev = config['app_conf']['static_version']

        # HAR initialization
        try:
            har = HAR( request.POST['file'].value )
        except:
            har = HAR( request.POST['file'] )
        
        # Check for initialization status
        if har.status == 'Successful':
            # Parsing imported HAR file
            har.analyze()
            
            # MongoDB handler
            mdb_handler = MongoDB()
            
            if config['app_conf']['ps_enabled'] == 'true':
                #Store HAR for Page Speed
                filename = os.path.join( config['app_conf']['temp_store'], hashlib.md5().hexdigest() )
                pagespeed_bin = os.path.join( config['app_conf']['bin_store'], "pagespeed_bin")
                outfile = filename + ".out"
                
                file = open(filename,'w')
                file.write(json.dumps(har.har))
                file.close()
                
                # Run pagespeed_bin
                os.system(pagespeed_bin + \
                    " -input_file " + \
                    filename + \
                    " -output_format formatted_json " + \
                    "-output_file " + \
                    outfile)
                
                # Output report (JSON)
                filename = outfile
                file = open(filename,'r')
                output = json.loads(file.read())
                file.close()

                # Page Speed scores
                scores = dict()
                
                scores['Total Score'] = int(output['score'])
                
                for rule in output['rule_results']:
                    scores[rule['localized_rule_name']]=int(rule['rule_score'])
            
            else:
                scores = dict()
                
                scores['Total Score'] = 100
            
            # Add document to collection
            mdb_handler.collection.insert({
                "label"         :har.label,
                "url"           :har.url,
                "timestamp"     :strftime("%Y-%m-%d %H:%M:%S", localtime()),
                "full_load_time":har.full_load_time,
                "total_size"    :har.total_size,
                "requests"      :har.requests,                
                "ps_scores"     :scores,
                "har"           :har.origin
            })

            try:
                if request.headers['automated'] == 'true': return 'Successful'
            except KeyError:
                redirect('/results/details?label=' + har.label) # redirect to details
        else:
            try:
                if request.headers['automated'] == 'true': return har.status # Return exception
            except KeyError:
                c.error = har.status
                return render('./upload.html') # Display error page

    def download(self):
        id = request.GET['id']

        filename = os.path.join( config['app_conf']['temp_store'], id )
        file = open(filename, 'r')
        data = file.read()
        file.close()

        data = "onInputData(" + data + ");"

        response.content_type = guess_type(filename)[0] or 'text/plain'
        return data