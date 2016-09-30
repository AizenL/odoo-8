from openerp.osv import fields, osv
import logging
_logger = logging.getLogger(__name__)

class stock_location(osv.osv):
    _inherit = "stock.location"

    _columns = {
        'additional_debit_account': fields.many2one('account.account', 'Additional debit account',
                                                   help="Si ces deux champs sont vides, le comportement par defaut de Odoo sera adopte. Sinon, le module virtual_location_inventory_account_move prend la releve et cree deux lignes supplementaires au account move line si la destination du move est cette location. "),
        'additional_credit_account': fields.many2one('account.account', 'Additional credit account',
                                                   help="Si ces deux champs sont vides, le comportement par defaut de Odoo sera adopte. Sinon, le module virtual_location_inventory_account_move prend la releve et cree deux lignes supplementaires au account move line si la destination du move est cette location."),
    }
    
class stock_quant(osv.osv):
    _inherit = "stock.quant"

    def _account_entry_move(self, cr, uid, quants, move, context=None):
        """
        Accounting Valuation Entries

        quants: browse record list of Quants to create accounting valuation entries for. Unempty and all quants are supposed to have the same location id (thay already moved in)
        move: Move to use. browse record
        """
        _logger.error("_account_entry_move NEW BEGIN")
        if context is None:
            context = {}
        location_obj = self.pool.get('stock.location')
        location_from = move.location_id
        location_to = quants[0].location_id
        company_from = location_obj._location_owner(cr, uid, location_from, context=context)
        company_to = location_obj._location_owner(cr, uid, location_to, context=context)

        if move.product_id.valuation != 'real_time':
            return False
        for q in quants:
            if q.owner_id:
                #if the quant isn't owned by the company, we don't make any valuation entry
                return False
            if q.qty <= 0:
                #we don't make any stock valuation for negative quants because the valuation is already made for the counterpart.
                #At that time the valuation will be made at the product cost price and afterward there will be new accounting entries
                #to make the adjustments when we know the real cost price.
                return False

        #in case of routes making the link between several warehouse of the same company, the transit location belongs to this company, so we don't need to create accounting entries
        # Create Journal Entry for products arriving in the company
        if company_to and (move.location_id.usage not in ('internal', 'transit') and move.location_dest_id.usage == 'internal' or company_from != company_to):
            ctx = context.copy()
            ctx['force_company'] = company_to.id

            journal_id, acc_src, acc_dest, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, context=ctx)
            


            if location_from and location_from.usage == 'customer':
                #goods returned from customer
                self._create_account_move_line(cr, uid, quants, move, acc_dest, acc_valuation, journal_id, context=ctx)
            else:
                self._create_account_move_line(cr, uid, quants, move, acc_src, acc_valuation, journal_id, context=ctx)

        # Create Journal Entry for products leaving the company
        if company_from and (move.location_id.usage == 'internal' and move.location_dest_id.usage not in ('internal', 'transit') or company_from != company_to):
            ctx = context.copy()
            ctx['force_company'] = company_from.id
            journal_id, acc_src, acc_dest, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, context=ctx)
           
            if location_to and location_to.usage == 'supplier':
                #goods returned to supplier
                _logger.error("    goods returned to supplier")
                self._create_account_move_line(cr, uid, quants, move, acc_valuation, acc_src, journal_id, context=ctx)
            
            elif move.location_dest_id.usage == 'inventory':
                _logger.error("    goods parties par type inventory")
                a_debiter, a_crediter = self._get_accounting_data_for_valuation_pt(cr, uid, move, context=ctx)
                _logger.error("    a_debiter :: %s", str(a_debiter))
                _logger.error("    a_crediter :: %s", str(a_crediter)) 
                
                if a_debiter != '' and a_crediter != '':
                    self._create_account_move_line_pt(cr, uid, quants, move, acc_valuation, acc_dest, journal_id, a_debiter, a_crediter, context=ctx)
                else:
                    self._create_account_move_line(cr, uid, quants, move, acc_valuation, acc_dest, journal_id, context=ctx)        
            
            else:
                _logger.error("    Il semble que le stock sort de la compagnie.")
                self._create_account_move_line(cr, uid, quants, move, acc_valuation, acc_dest, journal_id, context=ctx)
                
        _logger.error("_account_entry_move NEW END")

    def _get_accounting_data_for_valuation_pt(self, cr, uid, move, context=None):
        """
        Retourne les comptes pour combler un transfert interne vers une destination de location virtuelle de type inventaire (Ex. Depense en publicite). Il faut retourner le compte de stock_output (pour le debiter) et le compte d'achats (pour le crediter).
        """
        _logger.error("    _get_accounting_data_for_valuation_pt NEW BEGIN")
        _logger.error("        move.location_dest_id :: %s", str(move.location_dest_id))
        
        if move.location_dest_id.additional_credit_account:
                a_crediter = move.location_dest_id.additional_credit_account.id
        else:
            a_crediter =''
        _logger.error("        a_crediter :: %s", str(a_crediter))
                
        if move.location_dest_id.additional_debit_account:
                a_debiter = move.location_dest_id.additional_debit_account.id
        else:
            a_debiter = ''
        _logger.error("        a_debiter :: %s", str(a_debiter))

        _logger.error("    _get_accounting_data_for_valuation_pt NEW END")
        return  a_debiter, a_crediter

    def _create_account_move_line_pt(self, cr, uid, quants, move, credit_account_id, debit_account_id, journal_id, a_debiter, a_crediter, context=None):
        _logger.error("    _create_account_move_line_pt NEW BEGIN")
        #group quants by cost
        quant_cost_qty = {}
        for quant in quants:
            if quant_cost_qty.get(quant.cost):
                quant_cost_qty[quant.cost] += quant.qty
            else:
                quant_cost_qty[quant.cost] = quant.qty
        move_obj = self.pool.get('account.move')
        for cost, qty in quant_cost_qty.items():
            move_lines = self._prepare_account_move_line_pt(cr, uid, move, qty, cost, credit_account_id, debit_account_id, a_debiter, a_crediter, context=context)
            _logger.error("        move_lines :: %s", str(move_lines))
            period_id = context.get('force_period', self.pool.get('account.period').find(cr, uid, context=context)[0])
            move_obj.create(cr, uid, {'journal_id': journal_id,
                                      'line_id': move_lines,
                                      'period_id': period_id,
                                      'date': fields.date.context_today(self, cr, uid, context=context),
                                      'ref': move.picking_id.name}, context=context)
        _logger.error("    _create_account_move_line_pt NEW END")

    
    def _prepare_account_move_line_pt(self, cr, uid, move, qty, cost, credit_account_id, debit_account_id, a_debiter, a_crediter, context=None):
        """
        Generate the account.move.line values to post to track the stock valuation difference due to the
        processing of the given quant.
        """
        _logger.error("        _prepare_account_move_line_pt NEW BEGIN")
        if context is None:
            context = {}
        currency_obj = self.pool.get('res.currency')
        if context.get('force_valuation_amount'):
            valuation_amount = context.get('force_valuation_amount')
        else:
            if move.product_id.cost_method == 'average':
                valuation_amount = cost if move.location_id.usage != 'internal' and move.location_dest_id.usage == 'internal' else move.product_id.standard_price
            else:
                valuation_amount = cost if move.product_id.cost_method == 'real' else move.product_id.standard_price
        #the standard_price of the product may be in another decimal precision, or not compatible with the coinage of
        #the company currency... so we need to use round() before creating the accounting entries.
        valuation_amount = currency_obj.round(cr, uid, move.company_id.currency_id, valuation_amount * qty)
        partner_id = (move.picking_id.partner_id and self.pool.get('res.partner')._find_accounting_partner(move.picking_id.partner_id).id) or False
        debit_line_vals = {
                    'name': move.name,
                    'product_id': move.product_id.id,
                    'quantity': qty,
                    'product_uom_id': move.product_id.uom_id.id,
                    'ref': move.picking_id and move.picking_id.name or False,
                    'date': move.date,
                    'partner_id': partner_id,
                    'debit': valuation_amount > 0 and valuation_amount or 0,
                    'credit': valuation_amount < 0 and -valuation_amount or 0,
                    'account_id': debit_account_id,
        }
        credit_line_vals = {
                    'name': move.name,
                    'product_id': move.product_id.id,
                    'quantity': qty,
                    'product_uom_id': move.product_id.uom_id.id,
                    'ref': move.picking_id and move.picking_id.name or False,
                    'date': move.date,
                    'partner_id': partner_id,
                    'credit': valuation_amount > 0 and valuation_amount or 0,
                    'debit': valuation_amount < 0 and -valuation_amount or 0,
                    'account_id': credit_account_id,
        }
        debit_line_vals2 = {
                    'name': move.name,
                    'product_id': move.product_id.id,
                    'quantity': qty,
                    'product_uom_id': move.product_id.uom_id.id,
                    'ref': move.picking_id and move.picking_id.name or False,
                    'date': move.date,
                    'partner_id': partner_id,
                    'debit': valuation_amount > 0 and valuation_amount or 0,
                    'credit': valuation_amount < 0 and -valuation_amount or 0,
                    'account_id': a_debiter,
        }
        credit_line_vals2 = {
                    'name': move.name,
                    'product_id': move.product_id.id,
                    'quantity': qty,
                    'product_uom_id': move.product_id.uom_id.id,
                    'ref': move.picking_id and move.picking_id.name or False,
                    'date': move.date,
                    'partner_id': partner_id,
                    'credit': valuation_amount > 0 and valuation_amount or 0,
                    'debit': valuation_amount < 0 and -valuation_amount or 0,
                    'account_id': a_crediter,
        }
        _logger.error("        _prepare_account_move_line_pt NEW END")
        
        return [(0, 0, debit_line_vals), (0, 0, credit_line_vals), (0, 0, debit_line_vals2), (0, 0, credit_line_vals2)]