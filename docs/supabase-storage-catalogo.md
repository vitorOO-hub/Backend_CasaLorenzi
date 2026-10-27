# Fotos do catálogo no Supabase Storage

Antes de usar o envio de fotos, crie o bucket no Dashboard do Supabase em **Storage**:

- Nome: `catalogo-produtos`
- Público: sim (as imagens são exibidas na loja online)
- Tamanho máximo por arquivo: `5 MB`
- Tipos permitidos: `image/jpeg`, `image/png` e `image/webp`

Ao aplicar as migrations Alembic, a API cria as políticas de Storage: somente sessões com o claim
`papel=admin` podem enviar ou excluir objetos desse bucket. A leitura pública é necessária para as
fotos dos produtos na vitrine. O cliente usa a chave pública do Supabase e a sessão do usuário; nenhuma
chave privilegiada é enviada ao navegador.

Os objetos são gravados em pastas pelo UUID do produto e recebem nomes únicos. A URL pública é salva
em `produto.imagem_url`, e o texto alternativo em `produto.imagem_alt`. A migração não cria nem
altera o bucket diretamente por SQL; bucket e objetos devem ser gerenciados pelo Storage API/Dashboard.
