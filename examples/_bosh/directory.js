(function($) {
     var BOSH_SERVICE = '/bosh/http-bind',
         connection,
         _people,
         _template,
         _edit,
         _add;

     $(document).ready(function () {
         connection = $.strophe({ url: BOSH_SERVICE });
         connect('user@localhost', 'secret');

         _people = $('#people');
         _template = _people.find('.template')
             .remove().removeClass('template');
         $('#people tr').live('click', edit_person);

         _add = $('#add-person').click(add_person);
         _edit = $('#edit').submit(save_person);
     });

     function connected() {
         people('get', '', function(reply) {
             $.each(reply, function(index, data) {
                 _people.append(new_row(data));
             });
         });
     }

     function add_person(ev) {
         clear_form(_edit).show();
     }

     function edit_person(ev) {
         update_form(clear_form(_edit), $.data(this, 'person')).show();
     }

     function save_person(ev) {
         ev.preventDefault();
         people('set', [form_data(_edit)], function(reply) {
             _edit.hide();
             update_people(reply);
         });
     }

     function update_people(data) {
         $.each(data, function(index, data) {
             var row = $('#row-' + data.rowid);
             if (row.length)
                 row.replaceWith(new_row(data));
             else {
                 _people.append(new_row(data));
             }
         });
     }

     function new_row(data) {
         var result = _template.clone();
         result.attr('id', 'row-' + data.rowid);

         $.each(data, function(key, value) {
             result.find('.' + key).html(value || '');
         });

         return result.removeClass('template').data('person', data);
     }

     function form_data(form) {
         var data = {};
         form_fields(form).each(function() {
             data[this.name] = $(this).val();
         });
         return data;
     }

     function form_fields(form) {
         return form.find(':input:not(:submit)');
     }

     function clear_form(form) {
         form_fields(form).val('');
         return form;
     }

     function update_form(form, data) {
         form_fields(form).each(function() {
             $(this).val(data[this.name] || '');
         });
         return form;
     }

     // -------------------- Queries --------------------

     function people( type, data, success, error ){
         success = success || function(){};
         error = error || alert;
         send({
             type: type,
             method: 'people',
             data: JSON.stringify(data),
             success: function( elem, reply ) { success(JSON.parse(reply)); },
             error: function( message ) { error(message); }
         });
     }

     function send( opt ){
         send_iq({
             iq: make_iq(opt.type || 'get', opt.method, opt.data),
             success: function(iq) { handle_response(iq, opt.success); },
             error: function(iq) { handle_error(iq, opt.error); }
         });
     }

     function make_iq(type, method, query) {
         return $iq({ type: type })
             .c(method, { xmlns: 'urn:D' })
             .t(Base64.encode(query));
     }

     function handle_response(iq, k) {
         var elem = iq.childNodes[0];
         k(elem, Base64.decode(elem.textContent));
     }

     function handle_error(iq, k) {
         k($(iq).find('text').text());
     }

     // -------------------- BOSH --------------------

     function connect(jid, pass) {
         connection.connect(jid, pass, connecting);
         return connection;
     }

     function connecting(status) {
         if (status == Strophe.Status.CONNFAIL) {
             alert('Strophe failed to connect.');
         } else if (status == Strophe.Status.CONNECTED) {
             connected();
         }
     }

     function send_iq(opt) {
         return connection.sendIQ(
             opt.iq,
             opt.success,
             opt.error || iq_error,
             opt.timeout || 2000
         );
     }

     function iq_error(data) {
         console.error('IQ failed!', data);
     }

     $.strophe = function(settings) {
         return $.extend(new Strophe.Connection(settings.url), settings);
     };

 })(jQuery);

