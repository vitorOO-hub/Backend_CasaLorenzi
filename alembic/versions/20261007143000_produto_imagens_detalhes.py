"""catalogo: imagens e detalhes editoriais no banco

Revision ID: 20261007143000
Revises: 20261007130000
Create Date: 2026-10-07 14:30:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007143000"
down_revision: str | Sequence[str] | None = "20261007130000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUBIDA = (
    "ALTER TABLE public.produto ADD COLUMN IF NOT EXISTS imagem_url TEXT",
    "ALTER TABLE public.produto ADD COLUMN IF NOT EXISTS imagem_alt TEXT",
    "ALTER TABLE public.produto ADD COLUMN IF NOT EXISTS imagem_vestida_url TEXT",
    "ALTER TABLE public.produto ADD COLUMN IF NOT EXISTS tipo TEXT",
    "ALTER TABLE public.produto ADD COLUMN IF NOT EXISTS tecido TEXT",
    "ALTER TABLE public.produto ADD COLUMN IF NOT EXISTS tecelagem TEXT",
    "ALTER TABLE public.produto ADD COLUMN IF NOT EXISTS costurado_em TEXT",
    "ALTER TABLE public.produto ADD COLUMN IF NOT EXISTS nota TEXT",
    "ALTER TABLE public.produto ADD COLUMN IF NOT EXISTS cores JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE public.produto DROP CONSTRAINT IF EXISTS chk_produto_imagem_url_preenchida",
    "ALTER TABLE public.produto ADD CONSTRAINT chk_produto_imagem_url_preenchida "
    "CHECK (imagem_url IS NULL OR length(trim(imagem_url)) > 0)",
    "ALTER TABLE public.produto DROP CONSTRAINT IF EXISTS chk_produto_detalhes_completos",
    """
    ALTER TABLE public.produto ADD CONSTRAINT chk_produto_detalhes_completos CHECK (
        imagem_url IS NULL
        OR (
            length(trim(coalesce(imagem_alt, ''))) > 0
            AND length(trim(coalesce(tipo, ''))) > 0
            AND length(trim(coalesce(tecido, ''))) > 0
            AND length(trim(coalesce(tecelagem, ''))) > 0
            AND length(trim(coalesce(costurado_em, ''))) > 0
            AND length(trim(coalesce(nota, ''))) > 0
            AND jsonb_typeof(cores) = 'array'
            AND jsonb_array_length(cores) > 0
        )
    )
    """,
    """
    WITH dados(nome, imagem_url, imagem_vestida_url, tipo, tecido, tecelagem, costurado_em, nota, cores) AS (
        VALUES
        (
            'Camisa Linho Essencial',
            '/img/produtos/CL-0101.jpg',
            'https://images.unsplash.com/photo-1630952323180-98ad9a192e46?w=1400&q=80&auto=format&fit=crop',
            'Camisas de linho',
            'em linho lavado',
            'Linho irlandes',
            'Bom Retiro, SP',
            'Gola italiana que fica em pe sem gravata. Fica melhor a cada lavagem.',
            '[{"nome":"Branco giz","hex":"#f4f1ea"},{"nome":"Ceu de Minas","hex":"#8fa1b5"}]'::jsonb
        ),
        (
            'Camisa Oxford Bianca',
            '/img/produtos/CL-0102.jpg',
            'https://images.unsplash.com/photo-1781145822880-ab30339ac274?w=1400&q=80&auto=format&fit=crop',
            'Camisas oxford',
            'em oxford de algodao egipcio',
            'Fio egipcio, tecido em Americana, SP',
            'Bom Retiro, SP',
            'A camisa de todo dia, com botao de madreperola.',
            '[{"nome":"Branco giz","hex":"#f4f1ea"},{"nome":"Ceu de Minas","hex":"#8fa1b5"}]'::jsonb
        ),
        (
            'Calça Alfaiataria Torino',
            '/img/produtos/CL-0203.jpg',
            'https://images.unsplash.com/photo-1517445312882-bc9910d016b7?w=1400&q=80&auto=format&fit=crop',
            'Calcas de alfaiataria',
            'em la fria, cintura alta',
            'Biella, Italia',
            'Bom Retiro, SP',
            'Pregas viradas para dentro e barra feita na hora, na loja.',
            '[{"nome":"Areia de Ipanema","hex":"#d9c8a9"},{"nome":"Noite paulistana","hex":"#1b2a4a"}]'::jsonb
        ),
        (
            'Blazer Estruturado Modena',
            '/img/produtos/CL-0204.jpg',
            'https://images.unsplash.com/photo-1767609127923-14192f306af8?w=1400&q=80&auto=format&fit=crop',
            'Blazers',
            'em la fria pied-de-poule',
            'Biella, Italia',
            'Bom Retiro, SP',
            'Ombro natural, dois botoes e forro de cupro que respira.',
            '[{"nome":"Cafe","hex":"#6b4e36"},{"nome":"Noite paulistana","hex":"#1b2a4a"}]'::jsonb
        ),
        (
            'Vestido Midi Amalfi',
            '/img/produtos/CL-0305.jpg',
            'https://images.unsplash.com/photo-1770235622504-3851a96ac6ef?w=1400&q=80&auto=format&fit=crop',
            'Vestidos midi',
            'em crepe de viscose',
            'Crepe nacional, Blumenau, SC',
            'Atelie da Barra, RJ',
            'Comprimento midi que ajustamos a sua altura sem custo.',
            '[{"nome":"Vinho","hex":"#5a1e24"},{"nome":"Carvao","hex":"#1f1f1f"}]'::jsonb
        ),
        (
            'Vestido Slip Verona',
            '/img/produtos/CL-0306.jpg',
            'https://images.unsplash.com/photo-1613415873569-02bfdd371106?w=1400&q=80&auto=format&fit=crop',
            'Slip dresses',
            'em cetim de seda',
            'Como, Italia',
            'Atelie da Barra, RJ',
            'Alcas regulaveis e vies cortado a mao.',
            '[{"nome":"Champanhe","hex":"#e6d9c2"},{"nome":"Carvao","hex":"#1f1f1f"}]'::jsonb
        ),
        (
            'Tricô Gola Alta Bolonha',
            '/img/produtos/CL-0407.jpg',
            'https://images.unsplash.com/photo-1687275152975-52df19f931d0?w=1400&q=80&auto=format&fit=crop',
            'Tricos',
            'em merino extrafino',
            'Merino de 18,5 microns',
            'Malharia em Monte Siao, MG',
            'Fina o bastante para ir por baixo do blazer.',
            '[{"nome":"Areia de Ipanema","hex":"#d9c8a9"},{"nome":"Mate","hex":"#7a6a4f"}]'::jsonb
        ),
        (
            'Suéter Lã Merino Aosta',
            '/img/produtos/CL-0408.jpg',
            'https://images.unsplash.com/photo-1608984361471-ff566593088f?w=1400&q=80&auto=format&fit=crop',
            'Sueteres',
            'em la merino canelada',
            'Merino de 19 microns',
            'Malharia em Monte Siao, MG',
            'Ponto canelado que nao deforma no cotovelo.',
            '[{"nome":"Vinho","hex":"#5a1e24"},{"nome":"Mate","hex":"#7a6a4f"}]'::jsonb
        ),
        (
            'Trench Coat Milano',
            '/img/produtos/CL-0509.jpg',
            'https://images.unsplash.com/photo-1633821879282-0c4e91f96232?w=1400&q=80&auto=format&fit=crop',
            'Trench coats',
            'em gabardine de algodao',
            'Gabardine de algodao egipcio',
            'Bom Retiro, SP',
            'Cinto forrado e ombro que segura a garoa.',
            '[{"nome":"Areia de Ipanema","hex":"#d9c8a9"},{"nome":"Noite paulistana","hex":"#1b2a4a"}]'::jsonb
        ),
        (
            'Jaqueta Couro Firenze',
            '/img/produtos/CL-0510.jpg',
            'https://images.unsplash.com/photo-1700993443774-306a87b16ae1?w=1400&q=80&auto=format&fit=crop',
            'Jaquetas',
            'em couro de cordeiro',
            'Curtume em Franca, SP',
            'Franca, SP',
            'Couro que amacia e escurece com o uso.',
            '[{"nome":"Cafe","hex":"#6b4e36"},{"nome":"Carvao","hex":"#1f1f1f"}]'::jsonb
        ),
        (
            'Saia Plissada Como',
            '/img/produtos/CL-0611.jpg',
            'https://images.unsplash.com/photo-1573638687899-e2758e4a373f?w=1400&q=80&auto=format&fit=crop',
            'Saias plissadas',
            'em crepe plissado',
            'Crepe plissado permanente',
            'Atelie da Barra, RJ',
            'As pregas nao saem na lavagem.',
            '[{"nome":"Castanha","hex":"#8b7563"},{"nome":"Carvao","hex":"#1f1f1f"}]'::jsonb
        ),
        (
            'Bolsa Estruturada Lucca',
            '/img/produtos/CL-0712.jpg',
            'https://images.unsplash.com/photo-1649544284889-2c30c3267013?w=1400&q=80&auto=format&fit=crop',
            'Bolsas',
            'em couro curtido ao vegetal',
            'Curtume em Novo Hamburgo, RS',
            'Novo Hamburgo, RS',
            'Cabe um notebook de 13 polegadas e um guarda-chuva.',
            '[{"nome":"Vinho","hex":"#5a1e24"},{"nome":"Carvao","hex":"#1f1f1f"}]'::jsonb
        ),
        (
            'Cinto Couro Siena',
            '/img/produtos/CL-0713.jpg',
            'https://images.unsplash.com/photo-1776843370483-4f793bc14739?w=1400&q=80&auto=format&fit=crop',
            'Cintos',
            'em couro de cinto de 3,5 cm',
            'Curtume em Franca, SP',
            'Franca, SP',
            'Fivela de latao envelhecido, furos feitos na loja.',
            '[{"nome":"Tabaco","hex":"#4a3326"},{"nome":"Carvao","hex":"#1f1f1f"}]'::jsonb
        ),
        (
            'Mocassim Pádua',
            '/img/produtos/CL-0814.jpg',
            'https://images.unsplash.com/photo-1616243344308-04fb7e776cfe?w=1400&q=80&auto=format&fit=crop',
            'Mocassins',
            'em couro de bezerro',
            'Curtume em Franca, SP',
            'Franca, SP',
            'Montado a mao, com sola de couro e salto de borracha.',
            '[{"nome":"Cafe","hex":"#6b4e36"},{"nome":"Carvao","hex":"#1f1f1f"}]'::jsonb
        ),
        (
            'Bota Chelsea Asolo',
            '/img/produtos/CL-0815.jpg',
            'https://images.unsplash.com/photo-1777987601423-f350ac29b3e9?w=1400&q=80&auto=format&fit=crop',
            'Botas',
            'em camurca',
            'Curtume em Franca, SP',
            'Franca, SP',
            'Elastico lateral e sola que aguenta calcada molhada.',
            '[{"nome":"Cafe","hex":"#6b4e36"},{"nome":"Carvao","hex":"#1f1f1f"}]'::jsonb
        )
    )
    UPDATE public.produto p
    SET imagem_url = dados.imagem_url,
        imagem_alt = p.nome,
        imagem_vestida_url = dados.imagem_vestida_url,
        tipo = dados.tipo,
        tecido = dados.tecido,
        tecelagem = dados.tecelagem,
        costurado_em = dados.costurado_em,
        nota = dados.nota,
        cores = dados.cores,
        atualizado_em = now()
    FROM dados
    WHERE p.nome = dados.nome
    """,
    "CREATE INDEX IF NOT EXISTS idx_produto_catalogo_completo "
    "ON public.produto (ativo) WHERE imagem_url IS NOT NULL",
)

DESCIDA = (
    "DROP INDEX IF EXISTS public.idx_produto_catalogo_completo",
    "ALTER TABLE public.produto DROP CONSTRAINT IF EXISTS chk_produto_detalhes_completos",
    "ALTER TABLE public.produto DROP CONSTRAINT IF EXISTS chk_produto_imagem_url_preenchida",
    "ALTER TABLE public.produto DROP COLUMN IF EXISTS cores",
    "ALTER TABLE public.produto DROP COLUMN IF EXISTS nota",
    "ALTER TABLE public.produto DROP COLUMN IF EXISTS costurado_em",
    "ALTER TABLE public.produto DROP COLUMN IF EXISTS tecelagem",
    "ALTER TABLE public.produto DROP COLUMN IF EXISTS tecido",
    "ALTER TABLE public.produto DROP COLUMN IF EXISTS tipo",
    "ALTER TABLE public.produto DROP COLUMN IF EXISTS imagem_vestida_url",
    "ALTER TABLE public.produto DROP COLUMN IF EXISTS imagem_alt",
    "ALTER TABLE public.produto DROP COLUMN IF EXISTS imagem_url",
)


def upgrade() -> None:
    for comando in SUBIDA:
        op.execute(comando)


def downgrade() -> None:
    for comando in DESCIDA:
        op.execute(comando)
