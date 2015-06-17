# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2010 Tiny SPRL (<http://tiny.be>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from openerp.osv import fields
from openerp.osv import osv
from openerp import netsvc
import time
from datetime import timedelta
from datetime import datetime
from openerp.tools.translate import _
from openerp import SUPERUSER_ID
import sys



class mrp_production_workcenter_line(osv.osv):


    _name = 'mrp.production.workcenter.line'
    _inherit = 'mrp.production.workcenter.line'
    
    
    _columns = {
        'date_planned': fields.datetime('Date Planned', type='datetime'),
        'date_planned_end': fields.datetime('End Date Planned', type='datetime'),
    }
    
    
class mrp_production(osv.osv):

    _name = 'mrp.production'
    _inherit = 'mrp.production'
    
    
    _columns = {
        'date_planned_end': fields.datetime('End date planned', readonly=True, states={'draft':[('readonly',False)]}),
        'mrp_planning_organise': fields.boolean('Mrp lines alignment'),
        'mrp_planning_turn': fields.boolean('Mrp lines in turn'),
    }
    
    _defaults = {
        'mrp_planning_organise': False,
        'mrp_planning_turn': True,
    }
    
    
    
    def _action_compute_lines(self, cr, uid, ids, properties=None, context=None):
        
        """ Compute product_lines and workcenter_lines from BoM structure
        and add date_planned, date_planned_end values
        @return: product_lines
        """
        
        if properties is None:
            properties = []
        dates = []
        dates_end = []
        results = []
        prod_line_obj = self.pool.get('mrp.production.product.line')
        workcenter_line_obj = self.pool.get('mrp.production.workcenter.line')
        
        for production in self.browse(cr, uid, ids, context=context):
            #unlink product_lines
            prod_line_obj.unlink(cr, SUPERUSER_ID, [line.id for line in production.product_lines], context=context)
    
            #unlink workcenter_lines
            workcenter_line_obj.unlink(cr, SUPERUSER_ID, [line.id for line in production.workcenter_lines], context=context)

            res = self._prepare_lines(cr, uid, production, properties=properties, context=context)
            results = res[0] # product_lines
            results2 = self._action_compute_dates(cr, uid, res[0], res[1], production.product_qty, production.mrp_planning_organise, production.mrp_planning_turn, production.date_planned, properties=properties, context=context) # workcenter_lines

            for line in results2:
                dates.append(line['date_planned'])
                dates_end.append(line['date_planned_end'])
            if len(dates) > 0:
                self.write(cr, uid, production.id, {'date_planned': sorted(dates)[0]})
            if len(dates_end) > 0:
                self.write(cr, uid, production.id, {'date_planned_end': sorted(dates_end)[-1]})
                
            # reset product_lines in production order
            for line in results:
                line['production_id'] = production.id
                prod_line_obj.create(cr, uid, line)
    
            #reset workcenter_lines in production order
            for line in results2:
                line['production_id'] = production.id
                workcenter_line_obj.create(cr, uid, line)
        return results
        
        
    def _action_compute_dates(self, cr, uid, result, result2, qty, mrp_planning_organise, mrp_planning_turn, date_planned, properties=None, context=None):
        
        """ Add date_planned, date_planned_end values to workcenter_lines
        @return: product_lines
        """
        workcenter_lines = self.pool.get('mrp.production.workcenter.line')
        workcenters = self.pool.get('mrp.workcenter')
        products = self.pool.get('product.product')
        settings = self.pool.get('mrp.config.settings')
        calendar = workcenters.browse(cr, uid, [line['workcenter_id'] for line in result2][0], context=context).calendar_id.id

        
        res_lines = []
        delays = []
        planned_dates = []
        
        


        # Calculate delay from purchace
        for bom_line in result:
            if bom_line:
                qty_avail = products.read(cr, uid, bom_line['product_id'],['qty_available'])['qty_available']
                if bom_line['product_qty'] > qty_avail:
                    prod = products.browse(cr, uid, bom_line['product_id'], context=context)
                    if prod.seller_ids:
                        for supplier in prod.seller_ids:
                            delays.append(supplier.delay)
                            
        if delays:
            date_now = datetime.strptime(date_planned, '%Y-%m-%d %H:%M:%S') + timedelta(days=sorted(delays)[-1])
        else:
            date_now = datetime.strptime(date_planned, '%Y-%m-%d %H:%M:%S')
            
        planned = (date_now + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
            
        planned_end = (date_now + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
        
        if self._check_date_in_calendar(cr, uid, planned, calendar) == False:
            planned = self._first_date_in_calendar(cr, uid, planned, calendar)
        
        if self._check_date_in_calendar(cr, uid, planned_end, calendar) == False:
            planned_end = self._first_date_in_calendar(cr, uid, planned_end, calendar)
        

        for line in sorted(result2, key=lambda k: k['sequence']):
            workcenter_end_dates = workcenter_lines.search(cr, uid, ['&', ('workcenter_id', '=', line['workcenter_id']), ('date_planned_end', '!=', None),], order = 'date_planned_end')
            if workcenter_end_dates:
                workcenter_last_date = workcenter_lines.read(cr, uid, workcenter_end_dates[-1],['date_planned_end'])['date_planned_end']
                if workcenter_last_date > planned:
                    planned = workcenter_last_date
            delay = workcenters.browse(cr, uid, line['workcenter_id'], context=context).time_start + workcenters.browse(cr, uid, line['workcenter_id'], context=context).time_stop
            if delay:
                line['hour'] += delay
            calendar = workcenters.browse(cr, uid, line['workcenter_id'], context=context).calendar_id.id
            intervals = self.pool.get('resource.calendar').interval_get_multi(cr, uid, [(planned, line['hour'], calendar)])
            end_date = intervals.get((planned, line['hour'], calendar))
            if planned_end < end_date[-1][-1].strftime('%Y-%m-%d %H:%M:%S'):
                planned_end = end_date[-1][-1].strftime('%Y-%m-%d %H:%M:%S')
            line['date_planned'] = planned
            line['date_planned_end'] = planned_end
            res_lines.append(line)
            
            if mrp_planning_turn:
                planned = line['date_planned_end']
            else:
                if line['hour']/qty >= 1:
                    intervals_one_pc = self.pool.get('resource.calendar').interval_get_multi(cr, uid, [(line['date_planned'], line['hour']/qty, calendar)])
                    planned = intervals_one_pc.get((line['date_planned'], line['hour']/qty, calendar))[-1][-1].strftime('%Y-%m-%d %H:%M:%S')
                else:
                    planned_plus_hour = (datetime.strptime(line['date_planned'], '%Y-%m-%d %H:%M:%S') + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
                    planned = self._first_date_in_calendar(cr, uid, planned_plus_hour, calendar)

        if mrp_planning_organise:
            prev_line_date = False
            lines_start = []
            org_res_lines = []
            for res_line in sorted(res_lines, key=lambda k: k['sequence'], reverse=True):
                calendar = workcenters.browse(cr, uid, res_line['workcenter_id'], context=context).calendar_id.id
                if prev_line_date and datetime.strptime(res_line['date_planned'], '%Y-%m-%d %H:%M:%S') < prev_line_date - timedelta(res_line['hour']/qty) and res_line['hour']/qty >= 1:
                    date_delta_1 = (prev_line_date - timedelta(hours=res_line['hour'])).strftime('%Y-%m-%d %H:%M:%S')
                    res_line['date_planned'] = self._first_date_in_calendar(cr, uid, date_delta_1, calendar)
                    res_line['date_planned_end'] = self._last_date_in_calendar(cr, uid, res_line['date_planned'], res_line['hour'], calendar)
                    lines_start.append(res_line)
                    prev_line_date = datetime.strptime(res_line['date_planned'], '%Y-%m-%d %H:%M:%S')
                elif prev_line_date and datetime.strptime(res_line['date_planned'], '%Y-%m-%d %H:%M:%S') < prev_line_date - timedelta(hours=1):
                    date_delta_2 = (prev_line_date - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
                    res_line['date_planned'] = self._first_date_in_calendar(cr, uid, date_delta_2, calendar)
                    res_line['date_planned_end'] = self._last_date_in_calendar(cr, uid, res_line['date_planned'], res_line['hour'], calendar)
                    lines_start.append(res_line)
                    prev_line_date = datetime.strptime(res_line['date_planned'], '%Y-%m-%d %H:%M:%S')
                else:
                    lines_start.append(res_line)
                    prev_line_date = datetime.strptime(res_line['date_planned'], '%Y-%m-%d %H:%M:%S')


            prev_line_date_end = False
            for line in sorted(lines_start, key=lambda k: k['sequence']):
                calendar = workcenters.browse(cr, uid, line['workcenter_id'], context=context).calendar_id.id
                if prev_line_date_end and prev_line_date_end + timedelta(hours=(line['hour']/qty)) > datetime.strptime(self._last_date_in_calendar(cr, uid, line['date_planned'], line['hour'], calendar), '%Y-%m-%d %H:%M:%S'):
                    line['date_planned_end'] = self._last_date_in_calendar(cr, uid, prev_line_date_end.strftime('%Y-%m-%d %H:%M:%S'), line['hour']/qty, calendar)
                    prev_line_date_end = datetime.strptime(line['date_planned_end'], '%Y-%m-%d %H:%M:%S')
                    org_res_lines.append(line)
                else:
                    prev_line_date_end = datetime.strptime(line['date_planned_end'], '%Y-%m-%d %H:%M:%S')
                    org_res_lines.append(line)
                    
            res = org_res_lines
        else:
            res = res_lines
        return res

        
    def _check_date_in_calendar(self, cr, uid, date, calendar_id, properties=None, context=None):
        
        calendar = self.pool.get('resource.calendar')
        intervals = calendar.interval_get_multi(cr, uid, [(date, 240, calendar_id)])
        cal_date = intervals.get((date, 240, calendar_id))[0][0].strftime('%Y-%m-%d %H:%M:%S')
        if datetime.strptime(cal_date, '%Y-%m-%d %H:%M:%S') == datetime.strptime(date, '%Y-%m-%d %H:%M:%S'):
            return True
        else:
            return False
            
    
    def _last_date_in_calendar(self, cr, uid, date, hours, calendar_id, properties=None, context=None):
        
        calendar = self.pool.get('resource.calendar')
        intervals = calendar.interval_get_multi(cr, uid, [(date, hours, calendar_id)])
        cal_date = intervals.get((date, hours, calendar_id))[-1][-1].strftime('%Y-%m-%d %H:%M:%S')
        return cal_date
        
        
    def _first_date_in_calendar(self, cr, uid, date, calendar_id, properties=None, context=None):
        
        calendar = self.pool.get('resource.calendar')
        intervals = calendar.interval_get_multi(cr, uid, [(date, 240, calendar_id)])
        cal_date = intervals.get((date, 240, calendar_id))[0][0].strftime('%Y-%m-%d %H:%M:%S')
        return cal_date
        
