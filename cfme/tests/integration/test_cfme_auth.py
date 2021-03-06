import time

import pytest
from fauxfactory import gen_alphanumeric

from cfme import test_requirements
from cfme.base.credential import Credential
from cfme.utils.appliance.implementations.ui import navigate_to
from cfme.utils.auth import ActiveDirectoryAuthProvider
from cfme.utils.auth import AmazonAuthProvider
from cfme.utils.auth import auth_user_data
from cfme.utils.auth import FreeIPAAuthProvider
from cfme.utils.auth import OpenLDAPAuthProvider
from cfme.utils.auth import OpenLDAPSAuthProvider
from cfme.utils.blockers import BZ
from cfme.utils.blockers import GH
from cfme.utils.conf import auth_data
from cfme.utils.conf import credentials
from cfme.utils.log import logger
from cfme.utils.log_validator import LogValidator
from cfme.utils.wait import wait_for

pytestmark = [
    pytest.mark.uncollectif(lambda temp_appliance_preconfig_long:
                            temp_appliance_preconfig_long.is_pod,
                            reason='Tests not valid for podified'),
    pytest.mark.meta(blockers=[
        GH('ManageIQ/integration_tests:6465',
           # need SSL openldap server
           unblock=lambda auth_mode, prov_key: not (
               auth_mode in ['external', 'ldaps'] and
               auth_data.auth_providers[prov_key].type == 'openldaps')),
        BZ(1593171)]),  # 510z groups page doesn't load
    pytest.mark.browser_isolation,
    pytest.mark.long_running,
    pytest.mark.serial,
    pytest.mark.usefixtures(
        'prov_key', 'auth_mode', 'auth_provider', 'configure_auth', 'auth_user'
    ),
    test_requirements.auth
]

# map auth provider types, auth_modes, and user_types for test matrix
# first key level is auth mode
# second key level is provider type  (auth_provider key in parametrization)
# finally, user_types valid for testing on the above combination of provider+mode
test_param_maps = {
    'amazon': {
        AmazonAuthProvider.auth_type: {
            'user_types': ['username']}
    },
    'ldap': {
        ActiveDirectoryAuthProvider.auth_type: {
            # add cn_domain, samacct
            'user_types': ['cn', 'email', 'uid', 'upn']
        },
        FreeIPAAuthProvider.auth_type: {
            'user_types': ['cn', 'uid']  # add cn_domain
        },
        OpenLDAPAuthProvider.auth_type: {
            'user_types': ['cn', 'uid']  # add cn_domain
        }
    },
    'external': {
        FreeIPAAuthProvider.auth_type: {
            'user_types': ['uid']
        },
        OpenLDAPSAuthProvider.auth_type: {
            'user_types': ['uid']
        }
        # TODO add ActiveDirectory SAMAcct usertype for external
    }}


def pytest_generate_tests(metafunc):
    """ zipper auth_modes and auth_prov together and drop the nonsensical combos """
    # TODO use supportability and provider type+version parametrization
    argnames = ['auth_mode', 'prov_key', 'user_type', 'auth_user']
    argvalues = []
    idlist = []
    if 'auth_providers' not in auth_data:
        metafunc.parametrize(argnames, [
            pytest.param(
                None, None, None, None,
                marks=pytest.mark.uncollect(reason="auth providers data missing"))])
        return
    # Holy nested loops, batman
    # go through each mode, then each auth type, and find auth providers matching that type
    # go through each user type for the given mode+auth_type (from param_maps above)
    # for each user type, find users in the yaml matching user_type an on the given auth provider
    # add parametrization for matching set of mode, auth_provider key, user_type, and user_dict
    # set id, use the username from userdict instead of an auto-generated "auth_user[\d]" ID
    for mode in test_param_maps.keys():
        for auth_type in test_param_maps.get(mode, {}):
            eligible_providers = {key: prov_dict
                                  for key, prov_dict in auth_data.auth_providers.items()
                                  if prov_dict.type == auth_type}
            for user_type in test_param_maps[mode][auth_type]['user_types']:
                for key, prov_dict in eligible_providers.items():
                    for user_dict in [u for u in auth_user_data(key, user_type) or []]:
                        if user_type in prov_dict.get('user_types', []):
                            argvalues.append((mode, key, user_type, user_dict))
                            idlist.append('-'.join([mode, key, user_type, user_dict.username]))
    metafunc.parametrize(argnames, argvalues, ids=idlist)


@pytest.fixture(scope='function')
def user_obj(temp_appliance_preconfig_long, auth_user, user_type):
    """return a simple user object, see if it exists and delete it on teardown"""
    # Replace spaces with dashes in UPN type usernames for login compatibility
    username = auth_user.username.replace(' ', '-') if user_type == 'upn' else auth_user.username
    user = temp_appliance_preconfig_long.collections.users.simple_user(
        username,
        credentials[auth_user.password].password,
        fullname=auth_user.fullname or auth_user.username)  # fullname could be empty
    yield user

    temp_appliance_preconfig_long.browser.widgetastic.refresh()
    temp_appliance_preconfig_long.server.login_admin()
    if user.exists:
        user.delete()


@pytest.fixture
def log_monitor(user_obj, temp_appliance_preconfig_long):
    """Search evm.log for any plaintext password"""
    result = LogValidator(
        "/var/www/miq/vmdb/log/evm.log", failure_patterns=[f"{user_obj.credential.secret}"],
        hostname=temp_appliance_preconfig_long.hostname
    )
    result.start_monitoring()
    yield result


@pytest.mark.rhel_testing
@pytest.mark.tier(1)
@pytest.mark.uncollectif(lambda auth_mode, auth_user:
                         auth_mode == 'amazon' or
                         not any([True for g in auth_user.groups or [] if 'evmgroup' in g.lower()]),
                         reason='Amazon auth mode with default groups tested elsewhere,'
                                'or the auth user does not have an evm built-in group')
# this test only runs against users that have an evm built-in group
def test_login_evm_group(
        temp_appliance_preconfig_long, auth_user, user_obj, soft_assert, log_monitor
):
    """This test checks whether a user can login while assigned a default EVM group
        Prerequisities:
            * ``auth_data.yaml`` file
            * auth provider configured with user as a member of a group matching default EVM group
        Test will configure auth and login

    Polarion:
        assignee: dgaikwad
        casecomponent: Auth
        initialEstimate: 1/4h
    """
    # get a list of groups for the user that match evm default group names
    # Replace spaces with dashes in UPN type usernames for login compatibility
    evm_group_names = [group for group in auth_user.groups if 'evmgroup' in group.lower()]
    with user_obj:
        logger.info('Logging in as user %s, member of groups %s', user_obj, evm_group_names)
        view = navigate_to(temp_appliance_preconfig_long.server, 'LoggedIn')
        assert view.is_displayed, f'user {user_obj} failed login'
        soft_assert(user_obj.name == view.current_fullname,
                    f'user {user_obj} is not in view fullname')
        for name in evm_group_names:
            soft_assert(name in view.group_names,
                        f'user {user_obj} evm group {name} not in view group_names')

    # split loop to reduce number of logins
    temp_appliance_preconfig_long.server.login_admin()
    assert user_obj.exists, f'user record should have been created for "{user_obj}"'

    # assert no pwd in logs
    assert log_monitor.validate()


def retrieve_group(temp_appliance_preconfig_long, auth_mode, username, groupname, auth_provider,
        tenant=None):
    """Retrieve group from ext/ldap auth provider through UI

    Args:
        temp_appliance_preconfig_long: temp_appliance_preconfig_long object
        auth_mode: key from cfme.configure.configuration.server_settings.AUTH_MODES, parametrization
        user_data: user_data AttrDict from yaml, with username, groupname, password fields

    """
    group = temp_appliance_preconfig_long.collections.groups.instantiate(
        description=groupname,
        role='EvmRole-user',
        tenant=tenant,
        user_to_lookup=username,
        ldap_credentials=Credential(principal=auth_provider.bind_dn,
                                    secret=auth_provider.bind_password))
    add_method = ('add_group_from_ext_auth_lookup'
                  if auth_mode == 'external' else
                  'add_group_from_ldap_lookup')
    if not group.exists:
        getattr(group, add_method)()  # call method to add
        wait_for(lambda: group.exists)
    else:
        logger.info('User Group exists, skipping create: %r', group)
    return group


@pytest.mark.tier(1)
@pytest.mark.uncollectif(lambda auth_mode, auth_user:
                         auth_mode == 'amazon' or
                         not any(
                             [True for g in auth_user.groups or [] if 'evmgroup' not in g.lower()]
                         ),
                         reason='Amazon auth mode with default groups tested elsewhere,'
                                'or the auth user does not have an evm built-in group')
def test_login_retrieve_group(
        temp_appliance_preconfig_long, request, log_monitor,
        auth_mode, auth_provider, soft_assert, auth_user, user_obj
):
    """This test checks whether different cfme auth modes are working correctly.
       authmodes tested as part of this test: ext_ipa, ext_openldap, miq_openldap
       e.g. test_auth[ext-ipa_create-group]
        Prerequisities:
            * ``auth_data.yaml`` file
        Steps:
            * Make sure corresponding auth_modes data is updated to ``auth_data.yaml``
            * this test fetches the auth_modes from yaml and generates tests per auth_mode.

    Polarion:
        assignee: dgaikwad
        casecomponent: Auth
        initialEstimate: 1/4h
    """
    # get a list of (user_obj, groupname) tuples, creating the user object inline
    # filtering on those that do NOT evmgroup in groupname
    non_evm_group = [g for g in auth_user.groups or [] if 'evmgroup' not in g.lower()][0]
    # retrieving in test call and not fixture, getting the group from auth provider is part of test
    group = retrieve_group(
        temp_appliance_preconfig_long, auth_mode, auth_user.username, non_evm_group, auth_provider,
        tenant="My Company"  # tenant is required for group
    )

    with user_obj:
        view = navigate_to(temp_appliance_preconfig_long.server, 'LoggedIn')
        soft_assert(view.current_fullname == user_obj.name,
                    'user full name "{}" did not match UI display name "{}"'
                    .format(user_obj.name, view.current_fullname))
        soft_assert(group.description in view.group_names,
                    'user group "{}" not displayed in UI groups list "{}"'
                    .format(group.description, view.group_names))

    temp_appliance_preconfig_long.server.login_admin()  # context should get us back to admin
    assert user_obj.exists, f'User record for "{user_obj}" should exist after login'

    # assert no pwd in logs
    assert log_monitor.validate()

    @request.addfinalizer
    def _cleanup():
        if user_obj.exists:
            user_obj.delete()
        if group.exists:
            group.delete()


def format_user_principal(username, user_type, auth_provider):
    """Format CN/UID/UPN usernames for authentication with locally created groups"""
    if user_type == 'upn':
        return '{}@{}'.format(username.replace(' ', '-'),
                              auth_provider.user_types[user_type].user_suffix)
    elif user_type in ['uid', 'cn']:
        return '{}={},{}'.format(user_type,
                                 username,
                                 auth_provider.user_types[user_type].user_suffix)
    else:
        pytest.skip(f'No user formatting for {auth_provider} and user type {user_type}')


@pytest.fixture(scope='function')
def local_group(temp_appliance_preconfig_long):
    """Helper method to check for existance of a group and delete if need be"""
    group_name = gen_alphanumeric(length=15, start="test-group-")
    group = temp_appliance_preconfig_long.collections.groups.create(
        description=group_name, role='EvmRole-desktop'
    )
    assert group.exists
    yield group

    if group.exists:
        group.delete()


@pytest.fixture(scope='function')
def local_user(temp_appliance_preconfig_long, auth_user, user_type, auth_provider, local_group):
    # list of created users, instantiating the Credential and formatting the user name in loop
    user = temp_appliance_preconfig_long.collections.users.create(
        name=auth_user.fullname or auth_user.username,  # fullname could be empty
        credential=Credential(
            principal=format_user_principal(auth_user.username, user_type, auth_provider),
            secret=credentials[auth_user.password].password),
        groups=[local_group])

    yield user

    if user.exists:
        user.delete()


@pytest.fixture
def do_not_fetch_remote_groups(temp_appliance_preconfig_long):
    # modify auth settings to not get groups
    temp_appliance_preconfig_long.server.authentication.auth_settings = {
        'auth_settings': {'get_groups': False}
    }
    # this setting takes a bit to register, so wait 30 s
    time.sleep(30)
    yield
    # resetting settings not necessary as it's handled by the configure_auth fixture


@pytest.mark.tier(1)
@pytest.mark.uncollectif(lambda auth_mode: auth_mode == 'amazon',
                         reason='Amazon auth_data needed for local group testing')
def test_login_local_group(temp_appliance_preconfig_long, local_user, local_group, soft_assert,
                           do_not_fetch_remote_groups):
    """
    Test remote authentication with a locally created group.
    Group is NOT retrieved from or matched to those on authentication provider


    Polarion:
        assignee: dgaikwad
        initialEstimate: 1/4h
        casecomponent: Auth
    """
    with local_user:
        view = navigate_to(temp_appliance_preconfig_long.server, 'LoggedIn')
        soft_assert(view.current_fullname == local_user.name,
                    'user full name "{}" did not match UI display name "{}"'
                    .format(local_user.name, view.current_fullname))
        soft_assert(local_group.description in view.group_names,
                    'local group "{}" not displayed in UI groups list "{}"'
                    .format(local_group.description, view.group_names))


@pytest.mark.tier(1)
@pytest.mark.ignore_stream('5.8')
@pytest.mark.uncollectif(lambda auth_mode, auth_user:
                         auth_mode == 'amazon' or
                         len(auth_user.groups or []) < 2,
                         reason='Amazon auth_data needed for group switch testing or'
                         'user does not have multiple groups')
@pytest.mark.meta(blockers=[BZ(1759291)], automates=[1759291])
def test_user_group_switching(
        temp_appliance_preconfig_long, auth_user, auth_mode, auth_provider,
        soft_assert, request, user_obj, log_monitor
):
    """Test switching groups on a single user, between retreived group and built-in group

    Bugzilla:
        1759291

    Polarion:
        assignee: dgaikwad
        initialEstimate: 1/4h
        casecomponent: Auth
    """
    retrieved_groups = []
    for group in auth_user.groups:
        # pick non-evm group when there are multiple groups for the user
        if 'evmgroup' not in group.lower():
            # create group in CFME via retrieve_group which looks it up on auth_provider
            logger.info(f'Retrieving a user group that is non evm built-in: {group}')
            retrieved_groups.append(retrieve_group(temp_appliance_preconfig_long,
                                                   auth_mode,
                                                   auth_user.username,
                                                   group,
                                                   auth_provider))
    else:
        logger.info('All user groups for group switching are evm built-in: {}'
                    .format(auth_user.groups))

    with user_obj:
        view = navigate_to(temp_appliance_preconfig_long.server, 'LoggedIn')
        # Check there are multiple groups displayed
        assert len(view.group_names) > 1, 'Only a single group is displayed for the user'
        display_other_groups = [g for g in view.group_names if g != view.current_groupname]
        # check the user name is displayed
        soft_assert(view.current_fullname == user_obj.name,
                    'user full name "{}" did not match UI display name "{}"'
                    .format(auth_user, view.current_fullname))
        # Not checking current group, determined by group priority
        # check retrieved groups are there
        for group in retrieved_groups:
            soft_assert(group.description in view.group_names,
                        'user group "{}" not displayed in UI groups list "{}"'
                        .format(group, view.group_names))

        # change to the other groups
        for other_group in display_other_groups:
            soft_assert(other_group in auth_user.groups, 'Group {} in UI not expected for user {}'
                                                         .format(other_group, auth_user))
            view.change_group(other_group)
            assert view.is_displayed, ('Not logged in after switching to group {} for {}'
                                       .format(other_group, auth_user))
            # assert selected group has changed
            soft_assert(other_group == view.current_groupname,
                        'After switching to group {}, its not displayed as active'
                        .format(other_group))

    temp_appliance_preconfig_long.server.login_admin()
    assert user_obj.exists, f'User record for "{auth_user}" should exist after login'

    # assert no pwd in log
    assert log_monitor.validate()

    @request.addfinalizer
    def _cleanup():
        for group in retrieved_groups:
            if group.exists:
                group.delete()
