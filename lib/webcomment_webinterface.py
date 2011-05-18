# -*- coding: utf-8 -*-
## Comments and reviews for records.

## This file is part of Invenio.
## Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011 CERN.
##
## Invenio is free software; you can redistribute it and/or
## modify it under the terms of the GNU General Public License as
## published by the Free Software Foundation; either version 2 of the
## License, or (at your option) any later version.
##
## Invenio is distributed in the hope that it will be useful, but
## WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
## General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with Invenio; if not, write to the Free Software Foundation, Inc.,
## 59 Temple Place, Suite 330, Boston, MA 02111-1307, USA.

""" Comments and reviews for records: web interface """

__lastupdated__ = """$Date$"""

__revision__ = """$Id$"""

import cgi
from invenio.webcomment import check_recID_is_in_range, \
                               perform_request_display_comments_or_remarks, \
                               perform_request_add_comment_or_remark, \
                               perform_request_vote, \
                               perform_request_report, \
                               subscribe_user_to_discussion, \
                               unsubscribe_user_from_discussion, \
                               get_user_subscription_to_discussion, \
                               check_user_can_attach_file_to_comments, \
                               check_user_can_view_comments, \
                               check_user_can_send_comments, \
                               check_user_can_view_comment, \
                               query_get_comment
from invenio.config import \
     CFG_TMPDIR, \
     CFG_SITE_LANG, \
     CFG_SITE_URL, \
     CFG_PREFIX, \
     CFG_WEBCOMMENT_ALLOW_COMMENTS,\
     CFG_WEBCOMMENT_ALLOW_REVIEWS, \
     CFG_WEBCOMMENT_USE_MATHJAX_IN_COMMENTS, \
     CFG_SITE_RECORD
from invenio.webuser import getUid, page_not_authorized, isGuestUser, collect_user_info
from invenio.webpage import page, pageheaderonly, pagefooteronly
from invenio.search_engine import create_navtrail_links, \
     guess_primary_collection_of_a_record, \
     get_colID
from invenio.urlutils import redirect_to_url, \
                             make_canonical_urlargd
from invenio.htmlutils import get_mathjax_header
from invenio.errorlib import register_exception
from invenio.messages import gettext_set_language
from invenio.webinterface_handler import wash_urlargd, WebInterfaceDirectory
from invenio.websearchadminlib import get_detailed_page_tabs
from invenio.access_control_config import VIEWRESTRCOLL
from invenio.access_control_mailcookie import \
     mail_cookie_create_authorize_action, \
     mail_cookie_create_common, \
     mail_cookie_check_common, \
     InvenioWebAccessMailCookieDeletedError, \
     InvenioWebAccessMailCookieError
from invenio.webcomment_config import \
     CFG_WEBCOMMENT_MAX_ATTACHMENT_SIZE, \
     CFG_WEBCOMMENT_MAX_ATTACHED_FILES
import invenio.template
webstyle_templates = invenio.template.load('webstyle')
websearch_templates = invenio.template.load('websearch')
try:
    from invenio.fckeditor_invenio_connector import FCKeditorConnectorInvenio
    fckeditor_available = True
except ImportError, e:
    fckeditor_available = False
import os
from invenio import webinterface_handler_config as apache
from invenio.bibdocfile import \
     stream_file, \
     decompose_file, \
     propose_next_docname

class WebInterfaceCommentsPages(WebInterfaceDirectory):
    """Defines the set of /comments pages."""

    _exports = ['', 'display', 'add', 'vote', 'report', 'index', 'attachments',
                'subscribe', 'unsubscribe']

    def __init__(self, recid=-1, reviews=0):
        self.recid = recid
        self.discussion = reviews # 0:comments, 1:reviews
        self.attachments = WebInterfaceCommentsFiles(recid, reviews)

    def index(self, req, form):
        """
        Redirects to display function
        """
        return self.display(req, form)

    def display(self, req, form):
        """
        Display comments (reviews if enabled) associated with record having id recid where recid>0.
        This function can also be used to display remarks associated with basket having id recid where recid<-99.
        @param ln: language
        @param recid: record id, integer
        @param do: display order    hh = highest helpful score, review only
                                    lh = lowest helpful score, review only
                                    hs = highest star score, review only
                                    ls = lowest star score, review only
                                    od = oldest date
                                    nd = newest date
        @param ds: display since    all= no filtering by date
                                    nd = n days ago
                                    nw = n weeks ago
                                    nm = n months ago
                                    ny = n years ago
                                    where n is a single digit integer between 0 and 9
        @param nb: number of results per page
        @param p: results page
        @param voted: boolean, active if user voted for a review, see vote function
        @param reported: int, active if user reported a certain comment/review, see report function
        @param reviews: boolean, enabled for reviews, disabled for comments
        @param subscribed: int, 1 if user just subscribed to discussion, -1 if unsubscribed
        @return the full html page.
        """

        argd = wash_urlargd(form, {'do': (str, "od"),
                                   'ds': (str, "all"),
                                   'nb': (int, 100),
                                   'p': (int, 1),
                                   'voted': (int, -1),
                                   'reported': (int, -1),
                                   'subscribed': (int, 0),
                                   'cmtgrp': (list, ["latest"]) # 'latest' is now a reserved group/round name
                                   })

        _ = gettext_set_language(argd['ln'])
        uid = getUid(req)

        user_info = collect_user_info(req)
        (auth_code, auth_msg) = check_user_can_view_comments(user_info, self.recid)
        if auth_code and user_info['email'] == 'guest':
            cookie = mail_cookie_create_authorize_action(VIEWRESTRCOLL, {'collection' : guess_primary_collection_of_a_record(self.recid)})
            target = '/youraccount/login' + \
                make_canonical_urlargd({'action': cookie, 'ln' : argd['ln'], 'referer' : \
                CFG_SITE_URL + user_info['uri']}, {})
            return redirect_to_url(req, target, norobot=True)
        elif auth_code:
            return page_not_authorized(req, "../", \
                text = auth_msg)

        can_send_comments = False
        (auth_code, auth_msg) = check_user_can_send_comments(user_info, self.recid)
        if not auth_code:
            can_send_comments = True

        can_attach_files = False
        (auth_code, auth_msg) = check_user_can_attach_file_to_comments(user_info, self.recid)
        if not auth_code and (user_info['email'] != 'guest'):
            can_attach_files = True

        subscription = get_user_subscription_to_discussion(self.recid, uid)
        if subscription == 1:
            user_is_subscribed_to_discussion = True
            user_can_unsubscribe_from_discussion = True
        elif subscription == 2:
            user_is_subscribed_to_discussion = True
            user_can_unsubscribe_from_discussion = False
        else:
            user_is_subscribed_to_discussion = False
            user_can_unsubscribe_from_discussion = False

        #display_comment_rounds = [cmtgrp for cmtgrp in argd['cmtgrp'] if cmtgrp.isdigit() or cmtgrp == "all" or cmtgrp == "-1"]
        display_comment_rounds = argd['cmtgrp']

        check_warnings = []

        (ok, problem) = check_recID_is_in_range(self.recid, check_warnings, argd['ln'])
        if ok:
            (body, errors, warnings) = perform_request_display_comments_or_remarks(req=req, recID=self.recid,
                display_order=argd['do'],
                display_since=argd['ds'],
                nb_per_page=argd['nb'],
                page=argd['p'],
                ln=argd['ln'],
                voted=argd['voted'],
                reported=argd['reported'],
                subscribed=argd['subscribed'],
                reviews=self.discussion,
                uid=uid,
                can_send_comments=can_send_comments,
                can_attach_files=can_attach_files,
                user_is_subscribed_to_discussion=user_is_subscribed_to_discussion,
                user_can_unsubscribe_from_discussion=user_can_unsubscribe_from_discussion,
                display_comment_rounds=display_comment_rounds
                )

            unordered_tabs = get_detailed_page_tabs(get_colID(guess_primary_collection_of_a_record(self.recid)),
                                                    self.recid,
                                                    ln=argd['ln'])
            ordered_tabs_id = [(tab_id, values['order']) for (tab_id, values) in unordered_tabs.iteritems()]
            ordered_tabs_id.sort(lambda x, y: cmp(x[1], y[1]))
            link_ln = ''
            if argd['ln'] != CFG_SITE_LANG:
                link_ln = '?ln=%s' % argd['ln']
            tabs = [(unordered_tabs[tab_id]['label'], \
                     '%s/%s/%s/%s%s' % (CFG_SITE_URL, CFG_SITE_RECORD, self.recid, tab_id, link_ln), \
                     tab_id in ['comments', 'reviews'],
                     unordered_tabs[tab_id]['enabled']) \
                    for (tab_id, order) in ordered_tabs_id
                    if unordered_tabs[tab_id]['visible'] == True]
            top = webstyle_templates.detailed_record_container_top(self.recid,
                                                                    tabs,
                                                                    argd['ln'])
            bottom = webstyle_templates.detailed_record_container_bottom(self.recid,
                                                                         tabs,
                                                                         argd['ln'])

            title, description, keywords = websearch_templates.tmpl_record_page_header_content(req, self.recid, argd['ln'])
            navtrail = create_navtrail_links(cc=guess_primary_collection_of_a_record(self.recid), ln=argd['ln'])
            if navtrail:
                navtrail += ' &gt; '
            navtrail += '<a class="navtrail" href="%s/%s/%s?ln=%s">'% (CFG_SITE_URL, CFG_SITE_RECORD, self.recid, argd['ln'])
            navtrail += title
            navtrail += '</a>'
            navtrail += ' &gt; <a class="navtrail">%s</a>' % (self.discussion==1 and _("Reviews") or _("Comments"))

            mathjaxheader = ''
            if CFG_WEBCOMMENT_USE_MATHJAX_IN_COMMENTS:
                mathjaxheader = get_mathjax_header()
            jqueryheader = '''
            <script src="%(CFG_SITE_URL)s/js/jquery.min.js" type="text/javascript" language="javascript"></script>
            <script src="%(CFG_SITE_URL)s/js/jquery.MultiFile.pack.js" type="text/javascript" language="javascript"></script>
            ''' % {'CFG_SITE_URL': CFG_SITE_URL}


            return pageheaderonly(title=title,
                        navtrail=navtrail,
                        uid=uid,
                        verbose=1,
                        metaheaderadd = mathjaxheader + jqueryheader,
                        req=req,
                        language=argd['ln'],
                        navmenuid='search',
                        navtrail_append_title_p=0) + \
                    websearch_templates.tmpl_search_pagestart(argd['ln']) + \
                    top + body + bottom + \
                    websearch_templates.tmpl_search_pageend(argd['ln']) + \
                    pagefooteronly(lastupdated=__lastupdated__, language=argd['ln'], req=req)
        else:
            return page(title=_("Record Not Found"),
                        body=problem,
                        uid=uid,
                        verbose=1,
                        req=req,
                        language=argd['ln'],
                        warnings=check_warnings, errors=[],
                        navmenuid='search')

    # Return the same page wether we ask for /CFG_SITE_RECORD/123 or /CFG_SITE_RECORD/123/
    __call__ = index

    def add(self, req, form):
        """
        Add a comment (review) to record with id recid where recid>0
        Also works for adding a remark to basket with id recid where recid<-99
        @param ln: languange
        @param recid: record id
        @param action:  'DISPLAY' to display add form
                        'SUBMIT' to submit comment once form is filled
                        'REPLY' to reply to an already existing comment
        @param msg: the body of the comment/review or remark
        @param score: star score of the review
        @param note: title of the review
        @param comid: comment id, needed for replying
        @param editor_type: the type of editor used for submitting the
                            comment: 'textarea', 'fckeditor'.
        @param subscribe: if set, subscribe user to receive email
                          notifications when new comment are added to
                          this discussion
        @return the full html page.
        """
        argd = wash_urlargd(form, {'action': (str, "DISPLAY"),
                                   'msg': (str, ""),
                                   'note': (str, ''),
                                   'score': (int, 0),
                                   'comid': (int, 0),
                                   'editor_type': (str, ""),
                                   'subscribe': (str, ""),
                                   'cookie': (str, "")
                                   })
        _ = gettext_set_language(argd['ln'])

        actions = ['DISPLAY', 'REPLY', 'SUBMIT']
        uid = getUid(req)

        # Is site ready to accept comments?
        if uid == -1 or (not CFG_WEBCOMMENT_ALLOW_COMMENTS and not CFG_WEBCOMMENT_ALLOW_REVIEWS):
            return page_not_authorized(req, "../comments/add",
                                       navmenuid='search')

        # Is user allowed to post comment?
        user_info = collect_user_info(req)
        (auth_code_1, auth_msg_1) = check_user_can_view_comments(user_info, self.recid)
        (auth_code_2, auth_msg_2) = check_user_can_send_comments(user_info, self.recid)
        if isGuestUser(uid):
            cookie = mail_cookie_create_authorize_action(VIEWRESTRCOLL, {'collection' : guess_primary_collection_of_a_record(self.recid)})
            # Save user's value in cookie, so that these "POST"
            # parameters are not lost during login process
            msg_cookie = mail_cookie_create_common('comment_msg',
                                                    {'msg': argd['msg'],
                                                     'note': argd['note'],
                                                     'score': argd['score'],
                                                     'editor_type': argd['editor_type'],
                                                     'subscribe': argd['subscribe']},
                                                    onetime=True)
            target = '/youraccount/login' + \
                make_canonical_urlargd({'action': cookie, 'ln' : argd['ln'], 'referer' : \
                CFG_SITE_URL + user_info['uri'] + '&cookie=' + msg_cookie}, {})
            return redirect_to_url(req, target, norobot=True)
        elif (auth_code_1 or auth_code_2):
            return page_not_authorized(req, "../", \
                text = auth_msg_1 + auth_msg_2)

        user_info = collect_user_info(req)
        can_attach_files = False
        (auth_code, auth_msg) = check_user_can_attach_file_to_comments(user_info, self.recid)
        if not auth_code and (user_info['email'] != 'guest'):
            can_attach_files = True

        warning_msgs = []
        added_files = {}
        if can_attach_files:
            # User is allowed to attach files. Process the files
            file_too_big = False
            formfields = form.get('commentattachment[]', [])
            if not hasattr(formfields, "__getitem__"): # A single file was uploaded
                formfields = [formfields]
            for formfield in formfields[:CFG_WEBCOMMENT_MAX_ATTACHED_FILES]:
                if hasattr(formfield, "filename") and formfield.filename:
                    filename = formfield.filename
                    dir_to_open = os.path.join(CFG_TMPDIR, 'webcomment', str(uid))
                    try:
                        assert(dir_to_open.startswith(CFG_TMPDIR))
                    except AssertionError:
                        register_exception(req=req,
                                           prefix='User #%s tried to upload file to forbidden location: %s' \
                                           % (uid, dir_to_open))

                    if not os.path.exists(dir_to_open):
                        try:
                            os.makedirs(dir_to_open)
                        except:
                            register_exception(req=req, alert_admin=True)

                    ## Before saving the file to disc, wash the filename (in particular
                    ## washing away UNIX and Windows (e.g. DFS) paths):
                    filename = os.path.basename(filename.split('\\')[-1])
                    filename = filename.strip()
                    if filename != "":
                        # Check that file does not already exist
                        n = 1
                        while os.path.exists(os.path.join(dir_to_open, filename)):
                            basedir, name, extension = decompose_file(filename)
                            new_name = propose_next_docname(name)
                            filename = new_name + extension

                        fp = open(os.path.join(dir_to_open, filename), "w")
                        # FIXME: temporary, waiting for wsgi handler to be
                        # fixed. Once done, read chunk by chunk
##                         while formfield.file:
##                             fp.write(formfield.file.read(10240))
                        fp.write(formfield.file.read())
                        fp.close()
                        # Isn't this file too big?
                        file_size = os.path.getsize(os.path.join(dir_to_open, filename))
                        if CFG_WEBCOMMENT_MAX_ATTACHMENT_SIZE > 0 and \
                               file_size > CFG_WEBCOMMENT_MAX_ATTACHMENT_SIZE:
                            os.remove(os.path.join(dir_to_open, filename))
                            # One file is too big: record that,
                            # dismiss all uploaded files and re-ask to
                            # upload again
                            file_too_big = True
                            warning_msgs.append(('WRN_WEBCOMMENT_MAX_FILE_SIZE_REACHED', cgi.escape(filename), str(file_size/1024) + 'KB', str(CFG_WEBCOMMENT_MAX_ATTACHMENT_SIZE/1024) + 'KB'))
                        else:
                            added_files[filename] = os.path.join(dir_to_open, filename)

            if file_too_big:
                # One file was too big. Removed all uploaded filed
                for filepath in added_files.items():
                    try:
                        os.remove(filepath)
                    except:
                        # File was already removed or does not exist?
                        pass

        client_ip_address = req.remote_ip
        check_warnings = []
        (ok, problem) = check_recID_is_in_range(self.recid, check_warnings, argd['ln'])
        if ok:
            title, description, keywords = websearch_templates.tmpl_record_page_header_content(req,
                                                                                               self.recid,
                                                                                               argd['ln'])
            navtrail = create_navtrail_links(cc=guess_primary_collection_of_a_record(self.recid))
            if navtrail:
                navtrail += ' &gt; '
            navtrail += '<a class="navtrail" href="%s/%s/%s?ln=%s">'% (CFG_SITE_URL, CFG_SITE_RECORD, self.recid, argd['ln'])
            navtrail += title
            navtrail += '</a>'
            navtrail += '&gt; <a class="navtrail" href="%s/%s/%s/%s/?ln=%s">%s</a>' % (CFG_SITE_URL,
                                                                                           CFG_SITE_RECORD,
                                                                                           self.recid,
                                                                                           self.discussion==1 and 'reviews' or 'comments',
                                                                                           argd['ln'],
                                                                                           self.discussion==1 and _('Reviews') or _('Comments'))

            if argd['action'] not in actions:
                argd['action'] = 'DISPLAY'

            if not argd['msg']:
                # User had to login in-between, so retrieve msg
                # from cookie
                try:
                    (kind, cookie_argd) = mail_cookie_check_common(argd['cookie'],
                                                                    delete=True)

                    argd.update(cookie_argd)
                except InvenioWebAccessMailCookieDeletedError, e:
                    return redirect_to_url(req, CFG_SITE_URL + '/'+ CFG_SITE_RECORD +'/' + \
                                           str(self.recid) + (self.discussion==1 and \
                                                              '/reviews' or '/comments'))
                except InvenioWebAccessMailCookieError, e:
                    # Invalid or empty cookie: continue
                    pass

            subscribe = False
            if argd['subscribe'] and \
               get_user_subscription_to_discussion(self.recid, uid) == 0:
                # User is not already subscribed, and asked to subscribe
                subscribe = True

            (body, errors, warnings) = perform_request_add_comment_or_remark(recID=self.recid,
                                                                             ln=argd['ln'],
                                                                             uid=uid,
                                                                             action=argd['action'],
                                                                             msg=argd['msg'],
                                                                             note=argd['note'],
                                                                             score=argd['score'],
                                                                             reviews=self.discussion,
                                                                             comID=argd['comid'],
                                                                             client_ip_address=client_ip_address,
                                                                             editor_type=argd['editor_type'],
                                                                             can_attach_files=can_attach_files,
                                                                             subscribe=subscribe,
                                                                             req=req,
                                                                             attached_files=added_files,
                                                                             warnings=warning_msgs)

            if self.discussion:
                title = _("Add Review")
            else:
                title = _("Add Comment")

            jqueryheader = '''
            <script src="%(CFG_SITE_URL)s/js/jquery.min.js" type="text/javascript" language="javascript"></script>
            <script src="%(CFG_SITE_URL)s/js/jquery.MultiFile.pack.js" type="text/javascript" language="javascript"></script>
            ''' % {'CFG_SITE_URL': CFG_SITE_URL}

            return page(title=title,
                        body=body,
                        navtrail=navtrail,
                        uid=uid,
                        language=CFG_SITE_LANG,
                        verbose=1,
                        errors=errors,
                        warnings=warnings,
                        req=req,
                        navmenuid='search',
                        metaheaderadd=jqueryheader)
        # id not in range
        else:
            return page(title=_("Record Not Found"),
                        body=problem,
                        uid=uid,
                        verbose=1,
                        req=req,
                        warnings=check_warnings, errors=[],
                        navmenuid='search')

    def vote(self, req, form):
        """
        Vote positively or negatively for a comment/review.
        @param comid: comment/review id
        @param com_value:   +1 to vote positively
                            -1 to vote negatively
        @param recid: the id of the record the comment/review is associated with
        @param ln: language
        @param do: display order    hh = highest helpful score, review only
                                    lh = lowest helpful score, review only
                                    hs = highest star score, review only
                                    ls = lowest star score, review only
                                    od = oldest date
                                    nd = newest date
        @param ds: display since    all= no filtering by date
                                    nd = n days ago
                                    nw = n weeks ago
                                    nm = n months ago
                                    ny = n years ago
                                    where n is a single digit integer between 0 and 9
        @param nb: number of results per page
        @param p: results page
        @param referer: http address of the calling function to redirect to (refresh)
        @param reviews: boolean, enabled for reviews, disabled for comments
        """

        argd = wash_urlargd(form, {'comid': (int, -1),
                                   'com_value': (int, 0),
                                   'recid': (int, -1),
                                   'do': (str, "od"),
                                   'ds': (str, "all"),
                                   'nb': (int, 100),
                                   'p': (int, 1),
                                   'referer': (str, None)
                                   })

        client_ip_address = req.remote_ip
        uid = getUid(req)

        user_info = collect_user_info(req)
        (auth_code, auth_msg) = check_user_can_view_comments(user_info, self.recid)
        if auth_code and user_info['email'] == 'guest':
            cookie = mail_cookie_create_authorize_action(VIEWRESTRCOLL, {'collection' : guess_primary_collection_of_a_record(self.recid)})
            target = '/youraccount/login' + \
                make_canonical_urlargd({'action': cookie, 'ln' : argd['ln'], 'referer' : \
                CFG_SITE_URL + user_info['uri']}, {})
            return redirect_to_url(req, target, norobot=True)
        elif auth_code:
            return page_not_authorized(req, "../", \
                text = auth_msg)

        success = perform_request_vote(argd['comid'], client_ip_address, argd['com_value'], uid)
        if argd['referer']:
            argd['referer'] += "?ln=%s&amp;do=%s&amp;ds=%s&amp;nb=%s&amp;p=%s&amp;voted=%s&amp;" % (
                argd['ln'], argd['do'], argd['ds'], argd['nb'], argd['p'], success)
            redirect_to_url(req, argd['referer'])
        else:
            #Note: sent to comments display
            referer = "%s/%s/%s/%s?&amp;ln=%s&amp;voted=1"
            referer %= (CFG_SITE_URL, CFG_SITE_RECORD, self.recid, self.discussion == 1 and 'reviews' or 'comments', argd['ln'])
            redirect_to_url(req, referer)

    def report(self, req, form):
        """
        Report a comment/review for inappropriate content
        @param comid: comment/review id
        @param recid: the id of the record the comment/review is associated with
        @param ln: language
        @param do: display order    hh = highest helpful score, review only
                                    lh = lowest helpful score, review only
                                    hs = highest star score, review only
                                    ls = lowest star score, review only
                                    od = oldest date
                                    nd = newest date
        @param ds: display since    all= no filtering by date
                                    nd = n days ago
                                    nw = n weeks ago
                                    nm = n months ago
                                    ny = n years ago
                                    where n is a single digit integer between 0 and 9
        @param nb: number of results per page
        @param p: results page
        @param referer: http address of the calling function to redirect to (refresh)
        @param reviews: boolean, enabled for reviews, disabled for comments
        """

        argd = wash_urlargd(form, {'comid': (int, -1),
                                   'recid': (int, -1),
                                   'do': (str, "od"),
                                   'ds': (str, "all"),
                                   'nb': (int, 100),
                                   'p': (int, 1),
                                   'referer': (str, None)
                                   })

        client_ip_address = req.remote_ip
        uid = getUid(req)

        user_info = collect_user_info(req)
        (auth_code, auth_msg) = check_user_can_view_comments(user_info, self.recid)
        if auth_code or user_info['email'] == 'guest':
            cookie = mail_cookie_create_authorize_action(VIEWRESTRCOLL, {'collection' : guess_primary_collection_of_a_record(self.recid)})
            target = '/youraccount/login' + \
                make_canonical_urlargd({'action': cookie, 'ln' : argd['ln'], 'referer' : \
                CFG_SITE_URL + user_info['uri']}, {})
            return redirect_to_url(req, target, norobot=True)
        elif auth_code:
            return page_not_authorized(req, "../", \
                text = auth_msg)

        success = perform_request_report(argd['comid'], client_ip_address, uid)
        if argd['referer']:
            argd['referer'] += "?ln=%s&amp;do=%s&amp;ds=%s&amp;nb=%s&amp;p=%s&amp;reported=%s&amp;" % (argd['ln'], argd['do'], argd['ds'], argd['nb'], argd['p'], str(success))

            redirect_to_url(req, argd['referer'])
        else:
            #Note: sent to comments display
            referer = "%s/%s/%s/%s/display?ln=%s&amp;voted=1"
            referer %= (CFG_SITE_URL, CFG_SITE_RECORD, self.recid, self.discussion==1 and 'reviews' or 'comments', argd['ln'])
            redirect_to_url(req, referer)

    def subscribe(self, req, form):
        """
        Subscribe current user to receive email notification when new
        comments are added to current discussion.
        """
        argd = wash_urlargd(form, {'referer': (str, None)})

        uid = getUid(req)

        user_info = collect_user_info(req)
        (auth_code, auth_msg) = check_user_can_view_comments(user_info, self.recid)
        if isGuestUser(uid):
            cookie = mail_cookie_create_authorize_action(VIEWRESTRCOLL, {'collection' : guess_primary_collection_of_a_record(self.recid)})
            target = '/youraccount/login' + \
                make_canonical_urlargd({'action': cookie, 'ln' : argd['ln'], 'referer' : \
                CFG_SITE_URL + user_info['uri']}, {})
            return redirect_to_url(req, target, norobot=True)
        elif auth_code:
            return page_not_authorized(req, "../", \
                text = auth_msg)

        success = subscribe_user_to_discussion(self.recid, uid)
        display_url = "%s/%s/%s/comments/display?subscribed=%s&ln=%s" % \
                      (CFG_SITE_URL, CFG_SITE_RECORD, self.recid, str(success), argd['ln'])
        redirect_to_url(req, display_url)

    def unsubscribe(self, req, form):
        """
        Unsubscribe current user from current discussion.
        """
        argd = wash_urlargd(form, {'referer': (str, None)})

        user_info = collect_user_info(req)
        uid = getUid(req)

        if isGuestUser(uid):
            cookie = mail_cookie_create_authorize_action(VIEWRESTRCOLL, {'collection' : guess_primary_collection_of_a_record(self.recid)})
            target = '/youraccount/login' + \
                make_canonical_urlargd({'action': cookie, 'ln' : argd['ln'], 'referer' : \
                CFG_SITE_URL + user_info['uri']}, {})
            return redirect_to_url(req, target, norobot=True)

        success = unsubscribe_user_from_discussion(self.recid, uid)
        display_url = "%s/%s/%s/comments/display?subscribed=%s&ln=%s" % \
                      (CFG_SITE_URL, CFG_SITE_RECORD, self.recid, str(-success), argd['ln'])
        redirect_to_url(req, display_url)

class WebInterfaceCommentsFiles(WebInterfaceDirectory):
    """Handle <strike>upload and </strike> access to files for comments.

       <strike>The upload is currently only available through the FCKeditor.</strike>
    """

    #_exports = ['put'] # 'get' is handled by _lookup(..)

    def __init__(self, recid=-1, reviews=0):
        self.recid = recid
        self.discussion = reviews # 0:comments, 1:reviews

    def _lookup(self, component, path):
        """ This handler is invoked for the dynamic URLs (for getting
        <strike>and putting attachments</strike>) Eg:
        CFG_SITE_URL/CFG_SITE_RECORD/5953/comments/attachments/get/652/myfile.pdf
        """
        if component == 'get' and len(path) > 1:

            comid = path[0] # comment ID

            file_name = '/'.join(path[1:]) # the filename

            def answer_get(req, form):
                """Accessing files attached to comments."""
                form['file'] = file_name
                form['comid'] = comid
                return self._get(req, form)

            return answer_get, []

        # All other cases: file not found
        return None, []

    def _get(self, req, form):
        """
        Returns a file attached to a comment.

        Example:
        CFG_SITE_URL/CFG_SITE_RECORD/5953/comments/attachments/get/652/myfile.pdf
        where 652 is the comment ID
        """
        argd = wash_urlargd(form, {'file': (str, None),
                                   'comid': (int, 0)})
        _ = gettext_set_language(argd['ln'])

        # Can user view this record, i.e. can user access its
        # attachments?
        uid = getUid(req)
        user_info = collect_user_info(req)
        # Check that user can view record, and its comments (protected
        # with action "viewcomment")
        (auth_code, auth_msg) = check_user_can_view_comments(user_info, self.recid)
        if auth_code and user_info['email'] == 'guest':
            cookie = mail_cookie_create_authorize_action(VIEWRESTRCOLL, {'collection' : guess_primary_collection_of_a_record(self.recid)})
            target = '/youraccount/login' + \
                make_canonical_urlargd({'action': cookie, 'ln' : argd['ln'], 'referer' : \
                CFG_SITE_URL + user_info['uri']}, {})
            return redirect_to_url(req, target, norobot=True)
        elif auth_code:
            return page_not_authorized(req, "../", \
                                       text = auth_msg)

        # Does comment exist?
        if not query_get_comment(argd['comid']):
            req.status = apache.HTTP_NOT_FOUND
            return page(title=_("Page Not Found"),
                        body=_('The requested comment could not be found'),
                        req=req)

        # Check that user can view this particular comment, protected
        # using its own restriction
        (auth_code, auth_msg) = check_user_can_view_comment(user_info, argd['comid'])
        if auth_code and user_info['email'] == 'guest':
            cookie = mail_cookie_create_authorize_action(VIEWRESTRCOLL, {'collection' : guess_primary_collection_of_a_record(self.recid)})
            target = '/youraccount/login' + \
                make_canonical_urlargd({'action': cookie, 'ln' : argd['ln'], 'referer' : \
                CFG_SITE_URL + user_info['uri']}, {})
            return redirect_to_url(req, target)
        elif auth_code:
            return page_not_authorized(req, "../", \
                                       text = auth_msg,
                                       ln=argd['ln'])

        if not argd['file'] is None:
            # Prepare path to file on disk. Normalize the path so that
            # ../ and other dangerous components are removed.
            path = os.path.abspath(CFG_PREFIX + '/var/data/comments/' + \
                                   str(self.recid) + '/'  + str(argd['comid']) + \
                                   '/' + argd['file'])

            # Check that we are really accessing attachements
            # directory, for the declared record.
            if path.startswith(CFG_PREFIX + '/var/data/comments/' + \
                               str(self.recid)) and \
                   os.path.exists(path):
                return stream_file(req, path)

        # Send error 404 in all other cases
        req.status = apache.HTTP_NOT_FOUND
        return page(title=_("Page Not Found"),
                    body=_('The requested file could not be found'),
                    req=req,
                    language=argd['ln'])

##     def put(self, req, form):
##         """
##         Process requests received from FCKeditor to upload files, etc.
##         """
##         if not fckeditor_available:
##             return

##         uid = getUid(req)

##         # URL where the file can be fetched after upload
##         user_files_path = '%(CFG_SITE_URL)s/%(CFG_SITE_RECORD)s/%(recid)i/comments/attachments/get/%(uid)s' % \
##                           {'uid': uid,
##                            'recid': self.recid,
##                            'CFG_SITE_URL': CFG_SITE_URL}
##         # Path to directory where uploaded files are saved
##         user_files_absolute_path = '%(CFG_PREFIX)s/var/data/comments/%(recid)s/%(uid)s' % \
##                                    {'uid': uid,
##                                     'recid': self.recid,
##                                     'CFG_PREFIX': CFG_PREFIX}
##         # Create a Connector instance to handle the request
##         conn = FCKeditorConnectorInvenio(form, recid=self.recid, uid=uid,
##                                          allowed_commands=['QuickUpload'],
##                                          allowed_types = ['File', 'Image', 'Flash', 'Media'],
##                                          user_files_path = user_files_path,
##                                          user_files_absolute_path = user_files_absolute_path)

##         # Check that user can upload attachments for comments.
##         user_info = collect_user_info(req)
##         (auth_code, auth_msg) = check_user_can_attach_file_to_comments(user_info, self.recid)
##         if user_info['email'] == 'guest':
##             # User is guest: must login prior to upload
##             data = conn.sendUploadResults(1, '', '', 'Please login before uploading file.')
##         elif auth_code:
##             # User cannot submit
##             data = conn.sendUploadResults(1, '', '', 'Sorry, you are not allowed to submit files.')
##         else:
##             # Process the upload and get the response
##             data = conn.doResponse()

##         # Transform the headers into something ok for mod_python
##         for header in conn.headers:
##             if not header is None:
##                 if header[0] == 'Content-Type':
##                     req.content_type = header[1]
##                 else:
##                     req.headers_out[header[0]] = header[1]
##         # Send our response
##         req.send_http_header()
##         req.write(data)
