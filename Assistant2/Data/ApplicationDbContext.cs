using Microsoft.EntityFrameworkCore;
using AssistantDocumentaire1.Models;

namespace AssistantDocumentaire1.Data
{
    public class ApplicationDbContext : DbContext
    {
        public ApplicationDbContext(DbContextOptions<ApplicationDbContext> options)
            : base(options) { }

        public DbSet<Document> Documents { get; set; }
    }
}