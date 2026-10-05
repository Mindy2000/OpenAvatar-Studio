from test_app import create_avatar, make_client


def test_guided_answers_satisfy_section_checks_independent_of_question_titles(tmp_path):
    with make_client(tmp_path) as client:
        avatar = create_avatar(client, subject_kind='fictional')
        base = f"/api/avatars/{avatar['id']}"
        for key, answer in {
            'identity': '测试角色，21岁，大三学生，住在校园。',
            'personality': '温柔，自然，体贴，独立。',
            'speaking_style': '像恋人日常发消息，每次最多80字。',
            'boundaries': '完全原创虚构成年人，不对应真人，不编造未设定的经历。',
        }.items():
            assert client.post(base + '/guided-builder/answers', json={'question_key':key,'answer':answer}).status_code == 200
        report = client.get(base + '/checks').json()
        sections = {item['name']: item['passed'] for item in report['checks']}
        for name in ('身份', '核心性格', '说话风格', '边界与禁止事项', '原创/非真人声明'):
            assert sections[name], name
