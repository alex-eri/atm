import os
import subprocess
import codecs
import datetime
import shutil
import tempfile

class Pilot:
    def __init__(self, config):
        if config.get('demo'):
            distp = os.path.join(os.path.dirname(__file__), 'demo')
        else:
            distp = os.path.join(os.path.dirname(__file__), 'sb_pilot')
        self.installp = installp = config.get('install', tempfile.mkdtemp(prefix='sb_pilot'))
        shutil.copytree(distp, installp, dirs_exist_ok=True)
        os.chmod(os.path.join(installp, './sb_pilot' ), 0o555)
        try:
            os.chmod(os.path.join(installp, './upnixmn.out' ), 0o555)
            os.chmod(os.path.join(installp, './posScheduler' ), 0o555)
            os.symlink(config.get('com', '/dev/ttyPos0'), installp+'/ttyS99')
        except:
            pass

    def exec_sync(self):
        pilot, e, p = self.run(7)
        status, status_text = e[0].strip().split(',', maxsplit=1)
        return {
            'answer' : e,
            'message': p,
            'status': status,
            'status_text': status_text,
        }

    def run(self, *a):
        args = [str(i) for i in a]
        cwd = os.getcwd()
        os.chdir(self.installp)
        try:
            os.remove('e')
            os.remove('p')
        except FileNotFoundError:
            pass

        pilot = subprocess.run(
                ['./sb_pilot', *args],
                capture_output=True,
                encoding='koi8-r',
                check=True
            )

        try:
            e = codecs.open('e', encoding='koi8-r').read().splitlines()
        except Exception as err:
            return {'status_text': 'Нет ответа от терминала', 'status': '-2'}

        try:
            p = codecs.open('p', encoding='koi8-r').read()
        except:
            p = 'Нет чека'

        os.chdir(cwd)
        return pilot, e, p

    def exec_acquiring(self, ammount):
        SBERFRAC = int(os.environ.get('SBERFRAC', '100'))
        cwd = os.getcwd()
        os.chdir(self.installp)

        try:
            pilot, e, p = self.run('1', str(int(ammount*SBERFRAC)))
        except Exception as err:
            status_text = str(err)
            return {'status_text': status_text, 'status': '-1'}

        status, status_text = e[0].strip().split(',', maxsplit=1)

        if status == '2000':
            p = 'Отмененно клиентом'
        try:
            date = datetime.datetime.strptime(e[8].strip(), '%Y%m%d%H%M%S')
        except ValueError:
            date = datetime.datetime.now()

        dates = date.isoformat('T')

        ans = {
            'type': 'electronicaly',
            'answer' : e,
            'message': p,
            'status': status,
            'status_text': status_text,
            'card': e[1].strip(),
            'auth': e[3].strip(),
            'checkt': e[4].strip(),
            'terminal': e[7].strip(),
            'timet': dates,
            'link': e[9].strip(),
            'hash': e[10].strip(),
            'merchant': e[13].strip()
        }

        if status == '0':
            ans['ammount'] = ammount
        else:
            ans['ammount'] = 0

        return ans
