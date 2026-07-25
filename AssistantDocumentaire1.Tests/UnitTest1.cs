using Microsoft.EntityFrameworkCore;
using AssistantDocumentaire1.Data;
using AssistantDocumentaire1.Models;
using Xunit;

namespace AssistantDocumentaire1.Tests
{
    public class DocumentTests
    {
        [Fact]
        public void Document_ValeursParDefaut_SontCorrectes()
        {
            var document = new Document { Titre = "test.pdf" };

            Assert.Equal("test.pdf", document.Titre);
            Assert.False(document.EstIndexe);
            Assert.Equal(string.Empty, document.Chemin);
        }

        [Fact]
        public void ApplicationDbContext_SeConstruitSansErreur()
        {
            var options = new DbContextOptionsBuilder<ApplicationDbContext>()
                .UseInMemoryDatabase("TestDb")
                .Options;

            using var context = new ApplicationDbContext(options);

            Assert.NotNull(context.Documents);
        }
    }
}