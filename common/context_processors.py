from shorty.forms import SurlForm
from shorty.models import Domain, Surl


def global_shorty_context(request):
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {}

    form = None
    open_widget = False
    session_state = request.session.pop('global_quick_create_state', None)
    if session_state and session_state.get('next') == request.get_full_path():
        form = SurlForm(session_state.get('data') or None, user=request.user, allow_blank_alias=True)
        form.is_valid()
        open_widget = True
    elif session_state is not None:
        request.session['global_quick_create_state'] = session_state

    created_link_notice = None
    created_pk = (request.GET.get('created') or '').strip()
    if created_pk.isdigit():
        created_surl = Surl.objects.filter(pk=int(created_pk), domain__owner=request.user).only('pk', 'short_url').first()
        if created_surl:
            created_link_notice = {
                'pk': created_surl.pk,
                'short_url': created_surl.short_url,
            }

    verified_domains = Domain.objects.filter(owner=request.user, is_verified=True).order_by('name')

    return {
        'global_quick_create_available': True,
        'global_quick_create_form': form or SurlForm(user=request.user, allow_blank_alias=True),
        'global_quick_create_domains': verified_domains,
        'global_quick_create_open': open_widget,
        'created_link_notice': created_link_notice,
    }
