from django.db import migrations


SKILL_CATALOGUE = (
    ('Programming', 'PROGRAMMING', (
        'Python', 'JavaScript', 'Java', 'C#', 'C++', 'Go', 'PHP', 'Ruby', 'Rust',
        'Data Structures & Algorithms', 'Git & Version Control',
    )),
    ('Web Development', 'WEB_DEVELOPMENT', (
        'HTML & CSS', 'React', 'Node.js', 'Django', 'Flask', 'REST API Development',
        'Responsive Web Design',
    )),
    ('Database', 'DATABASE', (
        'SQL', 'PostgreSQL', 'MySQL', 'MongoDB', 'Database Design',
    )),
    ('Design', 'DESIGN', (
        'UI/UX Design', 'Figma', 'Graphic Design', 'Adobe Photoshop', 'Canva',
    )),
    ('Office Tools', 'OFFICE_TOOLS', (
        'Microsoft Excel', 'Microsoft Word', 'Microsoft PowerPoint', 'Google Sheets',
    )),
    ('Communication', 'COMMUNICATION', (
        'Public Speaking', 'Technical Writing', 'Presentation Skills', 'Teamwork',
        'Professional Communication',
    )),
    ('Music', 'MUSIC', (
        'Guitar', 'Piano', 'Music Theory', 'Singing',
    )),
    ('Photography', 'PHOTOGRAPHY', (
        'Portrait Photography', 'Product Photography', 'Photo Editing',
    )),
    ('Video Editing', 'VIDEO_EDITING', (
        'Video Editing', 'Adobe Premiere Pro', 'DaVinci Resolve',
    )),
    ('Other', 'OTHER', (
        'Data Analysis', 'Project Management', 'Research Skills', 'Critical Thinking',
        'Time Management', 'Resume Writing', 'Interview Preparation',
    )),
)


def add_catalogue_skills(apps, schema_editor):
    Skill = apps.get_model('skills', 'Skill')
    database = schema_editor.connection.alias

    for _, category, names in SKILL_CATALOGUE:
        for name in names:
            if not Skill.objects.using(database).filter(name__iexact=name).exists():
                Skill.objects.using(database).create(
                    name=name,
                    category=category,
                    is_active=True,
                )


class Migration(migrations.Migration):

    dependencies = [
        ('skills', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(add_catalogue_skills, migrations.RunPython.noop),
    ]
